#!/usr/bin/env python3
"""Auto-relay between the Lead (Claude Code) and the Reviewer (Codex) via HANDOFF.md.

State machine (driven only by the `狀態` line in HANDOFF.md):

  NOT_STARTED / IN_PROGRESS / CHANGES_REQUESTED  -> run Lead      (claude -p)
  APPROVED (milestone < M7)                       -> run Lead      (start next milestone)
  READY_FOR_REVIEW                                -> run Reviewer  (codex exec)
  NEEDS_HUMAN                                     -> stop and tell the human
  APPROVED at M7                                  -> done

Each agent run is one headless, stateless turn: all context lives in the repo files.
Usage:  python3 scripts/orchestrate.py [--repo PATH] [--max-steps N] [--no-push] [--dry-run]
"""
import argparse
import datetime
import hashlib
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

LEAD_STATES = {"NOT_STARTED", "IN_PROGRESS", "CHANGES_REQUESTED"}
KNOWN_STATES = LEAD_STATES | {"READY_FOR_REVIEW", "APPROVED", "NEEDS_HUMAN"}

COMMON_RULES = (
    "這是非互動的自動化執行：不要向使用者提問，不要等待回覆。"
    "只做這一輪該做的事，做完就結束。"
    "遇到 CLAUDE.md / AGENTS.md 裡的停止條件時，把問題寫進 HANDOFF.md 的 Needs human，"
    "把狀態改成 NEEDS_HUMAN，然後結束。"
    "不需要 git push，推送由外部流程處理。"
    "不要修改 PLAN.md 的範圍與驗收標準。"
)

LEAD_PROMPTS = {
    "NOT_STARTED": (
        "你是 Lead。請閱讀 CLAUDE.md、AGENTS.md、PLAN.md、HANDOFF.md，從 HANDOFF.md 指示的里程碑開始實作。"
        "完成後跑 make test 與 make lint，更新 HANDOFF.md（本輪紀錄、驗證結果、輪次、狀態改為 READY_FOR_REVIEW），"
        "小步 commit，然後結束。"
    ),
    "IN_PROGRESS": (
        "你是 Lead。請閱讀 CLAUDE.md、AGENTS.md、PLAN.md、HANDOFF.md，接續目前里程碑尚未完成的工作。"
        "完成後跑 make test 與 make lint，更新 HANDOFF.md，狀態改為 READY_FOR_REVIEW，commit，然後結束。"
    ),
    "CHANGES_REQUESTED": (
        "你是 Lead。Reviewer 已在 HANDOFF.md 的 Review 區塊留下意見。請閱讀 CLAUDE.md、AGENTS.md、HANDOFF.md，"
        "處理每一條 [blocking]（修正，或寫出有理由的反駁），[non-blocking] 可放進 Backlog。"
        "在『Lead 回應』區塊逐點回應，跑 make test 與 make lint，輪次 +1，狀態改為 READY_FOR_REVIEW，commit，然後結束。"
        "若輪次已超過 3 且仍有分歧，狀態改為 NEEDS_HUMAN 並說明分歧點。"
    ),
    "APPROVED": (
        "你是 Lead。上一個里程碑已經 APPROVED。請閱讀 CLAUDE.md、AGENTS.md、PLAN.md、HANDOFF.md，"
        "把已通過的里程碑記進『里程碑進度』表，把舊的本輪紀錄與 Review 移到『歷史輪次』，"
        "然後開始 PLAN.md 第 7 節的下一個里程碑：輪次重設為 1，實作、驗證、更新 HANDOFF.md，"
        "狀態改為 READY_FOR_REVIEW，commit，然後結束。"
    ),
}

REVIEWER_PROMPT = (
    "你是 Reviewer。請閱讀 AGENTS.md、PLAN.md、HANDOFF.md，嚴格依 AGENTS.md 的審查清單審查目前里程碑。"
    "你不可以實作功能或修改程式碼；你唯一可以編輯的檔案是 HANDOFF.md 的 Review 區塊與 Status 區塊。"
    "請實際執行 make test 與 make lint 驗證（網路可能被沙盒擋住，擋住時在意見中註明，不要當成失敗），"
    "並檢查 git log 與 git diff 找出本輪改動。"
    "把意見寫進 Review 區塊，每條標明 [blocking]、[non-blocking] 或 [question]；"
    "沒有 blocking 問題才可以把狀態改成 APPROVED，否則改成 CHANGES_REQUESTED。"
    "若本里程碑已經第 3 輪仍有 blocking 問題，狀態改成 NEEDS_HUMAN。"
    "不要執行 git commit 與 git push，外部流程會處理。"
)


def log(msg):
    print("[%s] %s" % (datetime.datetime.now().strftime("%H:%M:%S"), msg), flush=True)


def run(cmd, cwd, timeout=60, stdin=None):
    return subprocess.run(
        cmd, cwd=str(cwd), input=stdin, capture_output=True, text=True, timeout=timeout
    )


def read_state(repo):
    text = (repo / "HANDOFF.md").read_text(encoding="utf-8")
    head = text.split("## Needs human")[0]
    m = re.search(r"狀態[:：]\s*`?([A-Z_]+)`?", head)
    status = m.group(1) if m else "UNKNOWN"
    ms = re.search(r"當前里程碑[:：]\s*(M\d+)", head)
    rd = re.search(r"當前輪次[:：]\s*(\d+)\s*/\s*(\d+)", head)
    return {
        "status": status,
        "milestone": ms.group(1) if ms else "?",
        "round": "%s/%s" % (rd.group(1), rd.group(2)) if rd else "?",
        "hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "text": text,
    }


def needs_human_text(text):
    m = re.search(r"## Needs human[^\n]*\n(.*?)(?=\n## )", text, re.S)
    return m.group(1).strip() if m else "(看不到 Needs human 區塊，請直接打開 HANDOFF.md)"


def git_head(repo):
    r = run(["git", "rev-parse", "HEAD"], repo)
    return r.stdout.strip() if r.returncode == 0 else ""


def git_dirty(repo):
    r = run(["git", "status", "--porcelain"], repo)
    return bool(r.stdout.strip())


def ci_summary(repo):
    if not shutil.which("gh"):
        return "（本機沒有 gh，無法取得 CI 狀態）"
    try:
        r = run(
            ["gh", "run", "list", "--limit", "3", "--json",
             "name,status,conclusion,headSha,displayTitle"],
            repo, timeout=25,
        )
    except Exception as exc:  # noqa: BLE001
        return "（取得 CI 狀態失敗：%s）" % exc
    if r.returncode != 0:
        return "（gh 無法取得 CI 狀態：%s）" % r.stderr.strip()[:200]
    return r.stdout.strip()


def notify(title, body):
    try:
        subprocess.run(
            ["osascript", "-e",
             'display notification %s with title %s' % (_osa(body), _osa(title))],
            timeout=5, capture_output=True,
        )
    except Exception:  # noqa: BLE001
        pass


def _osa(s):
    return '"%s"' % s.replace("\\", "\\\\").replace('"', '\\"')


def auto_commit(repo, who):
    if not git_dirty(repo):
        return
    run(["git", "add", "-A"], repo)
    msg = "chore(handoff): auto-commit leftover changes after %s run" % who
    r = run(["git", "commit", "-q", "-m", msg], repo)
    if r.returncode == 0:
        log("已自動 commit %s 留下的未提交變更" % who)
    else:
        log("自動 commit 失敗：%s" % (r.stderr.strip() or r.stdout.strip())[:300])


def push(repo, state):
    if state.get("warned_push"):
        return
    r = run(["git", "push", "origin", "HEAD"], repo, timeout=120)
    if r.returncode == 0:
        log("已 push 到 origin")
    else:
        state["warned_push"] = True
        log("push 失敗（之後不再重複提示）：%s" % r.stderr.strip()[:300])


def run_agent(role, cmd, prompt, repo, logdir, timeout, stdin_prompt, step):
    logfile = logdir / ("%03d-%s.log" % (step, role.lower()))
    log("啟動 %s（上限 %d 分鐘），完整紀錄：%s" % (role, timeout // 60, logfile))
    started = time.time()
    try:
        r = subprocess.run(
            cmd, cwd=str(repo), input=prompt if stdin_prompt else None,
            capture_output=True, text=True, timeout=timeout,
        )
        out = "STDOUT:\n%s\n\nSTDERR:\n%s\n\nEXIT: %s\n" % (r.stdout, r.stderr, r.returncode)
        code = r.returncode
        tail = (r.stdout or r.stderr).strip().splitlines()[-12:]
    except subprocess.TimeoutExpired:
        out, code, tail = "TIMEOUT after %ds\n" % timeout, 124, ["(逾時)"]
    logfile.write_text(out, encoding="utf-8")
    log("%s 結束（exit %s，%d 秒）" % (role, code, int(time.time() - started)))
    for line in tail:
        print("    | " + line[:160])
    return code


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=None, help="repo 根目錄（預設：這支腳本的上一層）")
    ap.add_argument("--max-steps", type=int, default=40, help="最多執行幾次 agent（預設 40）")
    ap.add_argument("--timeout-min", type=int, default=45, help="單次 agent 上限分鐘數（預設 45）")
    ap.add_argument("--max-stalls", type=int, default=2, help="連續幾次沒有進展就停止（預設 2）")
    ap.add_argument("--no-push", action="store_true", help="不自動 git push")
    ap.add_argument("--dry-run", action="store_true", help="只印出會做什麼，不真的呼叫 agent")
    args = ap.parse_args()

    repo = Path(args.repo).resolve() if args.repo else Path(__file__).resolve().parent.parent
    if not (repo / "HANDOFF.md").exists():
        sys.exit("找不到 %s/HANDOFF.md，請確認 --repo 路徑。" % repo)

    lead_flags = shlex.split(os.environ.get(
        "LEAD_FLAGS", "--permission-mode auto --permission-prompts none"))
    reviewer_flags = shlex.split(os.environ.get(
        "REVIEWER_FLAGS", "--sandbox workspace-write"))

    for tool in ("claude", "codex"):
        if not shutil.which(tool) and not args.dry_run:
            sys.exit("找不到 %s 指令，請先安裝並登入。" % tool)

    logdir = repo / ".orchestrator" / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    exclude = repo / ".git" / "info" / "exclude"
    if exclude.exists() and ".orchestrator/" not in exclude.read_text(encoding="utf-8"):
        with exclude.open("a", encoding="utf-8") as f:
            f.write("\n.orchestrator/\n")

    lock = repo / ".orchestrator" / "lock"
    if lock.exists():
        sys.exit("偵測到 %s，可能已有另一個 orchestrator 在跑。確定沒有的話刪除該檔案再試。" % lock)
    lock.write_text(str(os.getpid()), encoding="utf-8")

    runtime = {}
    stalls = 0
    step = 0
    try:
        while step < args.max_steps:
            st = read_state(repo)
            log("狀態=%s 里程碑=%s 輪次=%s" % (st["status"], st["milestone"], st["round"]))

            if st["status"] == "NEEDS_HUMAN":
                msg = needs_human_text(st["text"])
                log("需要你處理，已停止。Needs human：\n%s" % msg)
                notify("quant-rank-dashboard：需要你處理", "請查看 HANDOFF.md")
                return 2
            if st["status"] == "APPROVED" and st["milestone"] == "M7":
                log("M7 已通過，全部完成。")
                notify("quant-rank-dashboard", "M0–M7 全部完成")
                return 0
            if st["status"] not in KNOWN_STATES:
                log("看不懂 HANDOFF.md 的狀態（%s），已停止。" % st["status"])
                return 3

            step += 1
            head_before, hash_before = git_head(repo), st["hash"]

            if st["status"] == "READY_FOR_REVIEW":
                role = "Reviewer"
                prompt = "%s\n%s\n\n最近的 CI 狀態（可能為空）：\n%s" % (
                    REVIEWER_PROMPT, COMMON_RULES, ci_summary(repo))
                cmd = ["codex", "exec"] + reviewer_flags + ["--cd", str(repo), "-"]
                stdin_prompt = True
            else:
                role = "Lead"
                key = "NOT_STARTED" if st["status"] == "NOT_STARTED" else st["status"]
                prompt = "%s\n%s" % (LEAD_PROMPTS[key], COMMON_RULES)
                cmd = ["claude", "-p", prompt] + lead_flags
                stdin_prompt = False

            if args.dry_run:
                log("[dry-run] 會執行 %s：%s" % (role, " ".join(shlex.quote(c) for c in cmd[:6]) + " ..."))
                return 0

            run_agent(role, cmd, prompt, repo, logdir, args.timeout_min * 60, stdin_prompt, step)
            auto_commit(repo, role)
            if not args.no_push:
                push(repo, runtime)

            after = read_state(repo)
            progressed = (after["hash"] != hash_before) or (git_head(repo) != head_before)
            stalls = 0 if progressed else stalls + 1
            if stalls >= args.max_stalls:
                log("連續 %d 次沒有任何進展（HANDOFF.md 與 commit 都沒變），已停止。請看 %s" % (stalls, logdir))
                notify("quant-rank-dashboard：卡住了", "請查看 .orchestrator/logs")
                return 4
            time.sleep(3)

        log("已達 --max-steps=%d，停止（避免無限執行）。要繼續請重新執行。" % args.max_steps)
        notify("quant-rank-dashboard", "達到步數上限，已停止")
        return 5
    except KeyboardInterrupt:
        log("收到 Ctrl+C，已停止。下次執行會從 HANDOFF.md 的狀態接續。")
        return 130
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
