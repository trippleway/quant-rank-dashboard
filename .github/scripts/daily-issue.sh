#!/usr/bin/env bash
# Keep one open "daily pipeline failing" issue: create it on the first failure, comment on
# later failures, close it when a run succeeds. Inputs come from daily.yml (notify job).
set -euo pipefail
: "${GITHUB_REPOSITORY:?}" "${RUN_URL:?}" "${PIPELINE_RESULT:?}" "${DEPLOY_RESULT:?}"

TITLE="daily pipeline failing"
existing=$(gh issue list --repo "$GITHUB_REPOSITORY" --state open --search "\"$TITLE\" in:title" \
  --json number,title --jq "map(select(.title == \"$TITLE\")) | .[0].number // empty")

if [[ "$PIPELINE_RESULT" == "success" && "$DEPLOY_RESULT" == "success" ]]; then
  if [[ -n "$existing" ]]; then
    gh issue comment "$existing" --repo "$GITHUB_REPOSITORY" --body "✅ 已恢復：$RUN_URL"
    gh issue close "$existing" --repo "$GITHUB_REPOSITORY"
  fi
  echo "daily run succeeded"
  exit 0
fi

body_file=$(mktemp)
{
  echo "### $(date -u +%Y-%m-%d) 每日 pipeline 失敗"
  echo
  echo "- Run（含完整 log）：$RUN_URL"
  echo "- pipeline job：\`$PIPELINE_RESULT\`；deploy job：\`$DEPLOY_RESULT\`"
  echo "- 網站維持上一次成功的部署，未發布本次資料。"
  if [[ "$PIPELINE_RESULT" == "success" ]]; then
    echo "- 部署失敗：若尚未啟用 GitHub Pages，請到 Settings → Pages → Build and deployment → Source 選「GitHub Actions」。"
  fi
  echo
  if [[ -f "${SUMMARY_FILE:-}" ]]; then
    cat "$SUMMARY_FILE"
  else
    echo "（沒有 qrd daily 摘要：失敗發生在 pipeline 執行前，請看 run log。）"
  fi
} >"$body_file"

if [[ -n "$existing" ]]; then
  gh issue comment "$existing" --repo "$GITHUB_REPOSITORY" --body-file "$body_file"
  echo "commented on issue #$existing"
else
  gh issue create --repo "$GITHUB_REPOSITORY" --title "$TITLE" --body-file "$body_file"
fi
