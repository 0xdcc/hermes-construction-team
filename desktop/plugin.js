/**
 * desktop/construction-team/plugin.js
 * Hermes 施工团队 (construction-team) 桌面 ES 模块插件
 *
 * 紧凑团队树、任务控制、按需打开主管会话、角色模型配置与发件箱监控。
 * 遵循 Hermes Desktop Plugin SDK 规范，纯 ESM，无构建步骤，使用 React.createElement (h)。
 */

import React, {
  createElement as h,
  useState,
  useEffect,
  useCallback,
  useMemo,
  useRef,
  Fragment
} from 'react'

import {
  host,
  ROUTES_AREA,
  SIDEBAR_NAV_AREA,
  PANES_AREA
} from '@hermes/plugin-sdk'

// 常量定义
const EMBEDDED_STYLES = "/* desktop/construction-team/style.css\n * Hermes \u65bd\u5de5\u56e2\u961f (construction-team) \u684c\u9762\u63d2\u4ef6\u7d27\u51d1\u6837\u5f0f\n * \u517c\u5bb9 Hermes \u6df1\u8272/\u6d45\u8272 CSS \u53d8\u91cf (Inter/mono/\u836f\u4e38\u72b6\u6001/\u65e0\u5bbd\u8868\u6298\u53e0)\n */\n\n.hct-root {\n  display: flex;\n  flex-direction: column;\n  height: 100%;\n  width: 100%;\n  background: var(--ui-panel-bg, var(--background, #121316));\n  color: var(--ui-text-primary, var(--foreground, #f3f4f6));\n  font-family: var(--font-sans, Inter, -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, sans-serif);\n  font-size: 13px;\n  line-height: 1.4;\n  letter-spacing: -0.01em;\n  box-sizing: border-box;\n  overflow: hidden;\n}\n\n.hct-root *, .hct-root *::before, .hct-root *::after {\n  box-sizing: border-box;\n}\n\n/* \u9876\u90e8\u7d27\u51d1\u6807\u9898\u680f */\n.hct-header {\n  display: flex;\n  align-items: center;\n  justify-content: space-between;\n  padding: 10px 14px;\n  border-bottom: 1px solid var(--ui-border, rgba(255, 255, 255, 0.08));\n  background: var(--ui-panel-header-bg, rgba(255, 255, 255, 0.02));\n  flex-shrink: 0;\n  gap: 12px;\n}\n\n.hct-header-left {\n  display: flex;\n  align-items: baseline;\n  gap: 8px;\n  min-width: 0;\n}\n\n.hct-title-zh {\n  font-size: 14px;\n  font-weight: 600;\n  color: var(--ui-text-primary, #fff);\n  white-space: nowrap;\n}\n\n.hct-subtitle-en {\n  font-size: 11px;\n  color: var(--ui-text-tertiary, #9ca3af);\n  text-transform: lowercase;\n  letter-spacing: 0;\n  font-family: var(--font-mono, ui-monospace, SFMono-Regular, monospace);\n  white-space: nowrap;\n}\n\n.hct-header-actions {\n  display: flex;\n  align-items: center;\n  gap: 6px;\n  flex-shrink: 0;\n}\n\n/* \u9519\u8bef\u4e0e\u8b66\u544a\u6761 */\n.hct-banner {\n  padding: 6px 12px;\n  font-size: 12px;\n  display: flex;\n  align-items: center;\n  justify-content: space-between;\n  gap: 8px;\n  flex-shrink: 0;\n}\n\n.hct-banner-error {\n  background: rgba(239, 68, 68, 0.15);\n  color: #fca5a5;\n  border-bottom: 1px solid rgba(239, 68, 68, 0.3);\n}\n\n.hct-banner-warning {\n  background: rgba(245, 158, 11, 0.15);\n  color: #fcd34d;\n  border-bottom: 1px solid rgba(245, 158, 11, 0.3);\n}\n\n/* \u4e3b\u5185\u5bb9\u53cc\u680f / \u5355\u680f\u5e03\u5c40 */\n.hct-main {\n  display: flex;\n  flex: 1;\n  min-height: 0;\n  overflow: hidden;\n}\n\n.hct-sidebar {\n  width: 260px;\n  min-width: 220px;\n  max-width: 340px;\n  border-right: 1px solid var(--ui-border, rgba(255, 255, 255, 0.08));\n  display: flex;\n  flex-direction: column;\n  background: var(--ui-sidebar-bg, rgba(0, 0, 0, 0.12));\n}\n\n.hct-content {\n  flex: 1;\n  min-width: 0;\n  display: flex;\n  flex-direction: column;\n  overflow-y: auto;\n  padding: 14px;\n  gap: 14px;\n}\n\n/* \u56e2\u961f\u5217\u8868 */\n.hct-team-list {\n  flex: 1;\n  overflow-y: auto;\n  padding: 8px;\n  display: flex;\n  flex-direction: column;\n  gap: 4px;\n}\n\n.hct-team-item {\n  display: flex;\n  flex-direction: column;\n  padding: 8px 10px;\n  border-radius: 6px;\n  cursor: pointer;\n  border: 1px solid transparent;\n  transition: all 0.15s ease;\n  gap: 4px;\n}\n\n.hct-team-item:hover {\n  background: var(--chrome-action-hover, rgba(255, 255, 255, 0.05));\n}\n\n.hct-team-item.hct-active {\n  background: var(--ui-panel-item-active, rgba(99, 102, 241, 0.12));\n  border-color: var(--ui-accent, #6366f1);\n}\n\n.hct-team-item-top {\n  display: flex;\n  align-items: center;\n  justify-content: space-between;\n  gap: 6px;\n}\n\n.hct-team-name {\n  font-weight: 500;\n  font-size: 13px;\n  color: var(--ui-text-primary, #fff);\n  overflow: hidden;\n  text-overflow: ellipsis;\n  white-space: nowrap;\n}\n\n.hct-team-item-meta {\n  display: flex;\n  align-items: center;\n  justify-content: space-between;\n  font-size: 11px;\n  color: var(--ui-text-tertiary, #9ca3af);\n}\n\n/* \u72b6\u6001\u836f\u4e38 (Pills) */\n.hct-pill {\n  display: inline-flex;\n  align-items: center;\n  padding: 1px 7px;\n  border-radius: 9999px;\n  font-size: 11px;\n  font-weight: 500;\n  line-height: 16px;\n  white-space: nowrap;\n  letter-spacing: -0.01em;\n}\n\n.hct-pill-accepted, .hct-pill-approved {\n  background: rgba(34, 197, 94, 0.15);\n  color: #4ade80;\n  border: 1px solid rgba(34, 197, 94, 0.3);\n}\n\n.hct-pill-active {\n  background: rgba(16, 185, 129, 0.15);\n  color: #34d399;\n  border: 1px solid rgba(16, 185, 129, 0.3);\n}\n\n.hct-pill-running {\n  background: rgba(56, 189, 248, 0.15);\n  color: #38bdf8;\n  border: 1px solid rgba(56, 189, 248, 0.3);\n}\n\n.hct-pill-completed {\n  background: rgba(59, 130, 246, 0.15);\n  color: #60a5fa;\n  border: 1px solid rgba(59, 130, 246, 0.3);\n}\n\n.hct-pill-paused, .hct-pill-unknown, .hct-pill-needs-reconcile, .hct-pill-needs_reconcile {\n  background: rgba(245, 158, 11, 0.15);\n  color: #fbbf24;\n  border: 1px solid rgba(245, 158, 11, 0.3);\n}\n\n.hct-pill-interrupted, .hct-pill-stopped, .hct-pill-failed, .hct-pill-rejected, .hct-pill-blocked {\n  background: rgba(239, 68, 68, 0.15);\n  color: #f87171;\n  border: 1px solid rgba(239, 68, 68, 0.3);\n}\n\n.hct-pill-pending, .hct-pill-dispatched, .hct-pill-idle {\n  background: rgba(148, 163, 184, 0.15);\n  color: #cbd5e1;\n  border: 1px solid rgba(148, 163, 184, 0.3);\n}\n\n.hct-pill-candidate, .hct-pill-review_pending, .hct-pill-awaiting_review {\n  background: rgba(168, 85, 247, 0.15);\n  color: #c084fc;\n  border: 1px solid rgba(168, 85, 247, 0.3);\n}\n\n/* \u6309\u94ae\u89c4\u8303 */\n.hct-btn {\n  display: inline-flex;\n  align-items: center;\n  justify-content: center;\n  padding: 4px 10px;\n  font-size: 12px;\n  font-weight: 500;\n  border-radius: 5px;\n  border: 1px solid var(--ui-border, rgba(255, 255, 255, 0.12));\n  background: var(--ui-button-bg, rgba(255, 255, 255, 0.05));\n  color: var(--ui-text-primary, #f3f4f6);\n  cursor: pointer;\n  transition: all 0.15s ease;\n  line-height: 1.2;\n  white-space: nowrap;\n}\n\n.hct-btn:hover:not(:disabled) {\n  background: var(--chrome-action-hover, rgba(255, 255, 255, 0.1));\n  border-color: var(--ui-border-hover, rgba(255, 255, 255, 0.25));\n}\n\n.hct-btn:disabled {\n  opacity: 0.45;\n  cursor: not-allowed;\n}\n\n.hct-btn-primary {\n  background: var(--ui-accent, #6366f1);\n  border-color: var(--ui-accent, #6366f1);\n  color: #ffffff;\n}\n\n.hct-btn-primary:hover:not(:disabled) {\n  background: #4f46e5;\n  border-color: #4f46e5;\n}\n\n.hct-btn-danger {\n  background: rgba(239, 68, 68, 0.15);\n  border-color: rgba(239, 68, 68, 0.3);\n  color: #f87171;\n}\n\n.hct-btn-danger:hover:not(:disabled) {\n  background: rgba(239, 68, 68, 0.3);\n  border-color: #ef4444;\n}\n\n.hct-btn-xs {\n  padding: 2px 6px;\n  font-size: 11px;\n}\n\n/* \u5361\u7247\u4e0e\u6a21\u5757\u9762\u677f */\n.hct-card {\n  background: var(--ui-card-bg, rgba(255, 255, 255, 0.03));\n  border: 1px solid var(--ui-border, rgba(255, 255, 255, 0.07));\n  border-radius: 8px;\n  overflow: hidden;\n  flex-shrink: 0;\n}\n\n.hct-card-header {\n  display: flex;\n  align-items: center;\n  justify-content: space-between;\n  padding: 8px 12px;\n  background: rgba(255, 255, 255, 0.015);\n  border-bottom: 1px solid var(--ui-border, rgba(255, 255, 255, 0.05));\n}\n\n.hct-card-title {\n  font-size: 12px;\n  font-weight: 600;\n  display: flex;\n  align-items: center;\n  gap: 6px;\n  color: var(--ui-text-primary, #f9fafb);\n}\n\n.hct-card-body {\n  padding: 10px 12px;\n}\n\n/* \u6811\u5f62\u89c6\u56fe\u89c4\u8303 (\u7b2c\u4e00\u7ea7\u603b\u63a7Root / \u7b2c\u4e8c\u7ea7\u4e3b\u7ba1Supervisors / \u7b2c\u4e09\u7ea7Workers\u4e0eTasks) */\n.hct-tree {\n  display: flex;\n  flex-direction: column;\n  gap: 8px;\n}\n\n.hct-tree-root {\n  border: 1px solid var(--ui-border, rgba(255, 255, 255, 0.1));\n  border-radius: 8px;\n  background: var(--ui-card-bg, rgba(255, 255, 255, 0.02));\n  overflow: hidden;\n  display: flex;\n  flex-direction: column;\n}\n\n.hct-tree-root-header {\n  display: flex;\n  align-items: center;\n  justify-content: space-between;\n  padding: 10px 14px;\n  background: rgba(255, 255, 255, 0.03);\n  border-bottom: 1px solid var(--ui-border, rgba(255, 255, 255, 0.08));\n  user-select: none;\n}\n\n.hct-tree-root-body {\n  padding: 10px 12px;\n  display: flex;\n  flex-direction: column;\n  gap: 10px;\n}\n\n.supervisors, .hct-supervisors {\n  display: flex;\n  flex-direction: column;\n  gap: 8px;\n}\n\n.hct-tree-node {\n  border: 1px solid var(--ui-border, rgba(255, 255, 255, 0.07));\n  border-left: 3px solid var(--ui-accent, #6366f1);\n  border-radius: 6px;\n  background: rgba(255, 255, 255, 0.015);\n  overflow: hidden;\n  padding: 4px 8px;\n}\n\n.hct-tree-header {\n  display: flex;\n  align-items: center;\n  justify-content: space-between;\n  padding: 6px 4px;\n  cursor: pointer;\n  user-select: none;\n}\n\n.hct-tree-branch {\n  margin-top: 6px;\n  padding-left: 12px;\n  border-left: 1px dashed var(--ui-border, rgba(255, 255, 255, 0.12));\n  display: flex;\n  flex-direction: column;\n  gap: 8px;\n}\n\n/* \u987e\u95ee\u65c1\u8def Sidecar (\u53ea\u8bfb\u65e0Worker) */\n.hct-advisor-sidecar {\n  display: flex;\n  flex-direction: column;\n  gap: 6px;\n  padding: 8px 12px;\n  background: rgba(168, 85, 247, 0.05);\n  border: 1px solid rgba(168, 85, 247, 0.2);\n  border-radius: 6px;\n}\n\n.hct-advisor-card {\n  display: flex;\n  align-items: center;\n  justify-content: space-between;\n  font-size: 12px;\n}\n\n.hct-badge-advisor {\n  display: inline-flex;\n  align-items: center;\n  padding: 1px 6px;\n  border-radius: 4px;\n  font-size: 10px;\n  font-weight: 500;\n  background: rgba(168, 85, 247, 0.2);\n  color: #c084fc;\n  border: 1px solid rgba(168, 85, 247, 0.4);\n}\n\n.hct-worker-list {\n  display: flex;\n  flex-direction: column;\n  gap: 4px;\n  margin-top: 4px;\n  padding-left: 6px;\n}\n\n.hct-worker-card {\n  display: flex;\n  align-items: center;\n  justify-content: space-between;\n  padding: 6px 8px;\n  background: rgba(255, 255, 255, 0.02);\n  border: 1px solid var(--ui-border, rgba(255, 255, 255, 0.05));\n  border-radius: 4px;\n  font-size: 12px;\n}\n\n/* \u8868\u5355\u63a7\u4ef6 */\n.hct-form-group {\n  display: flex;\n  flex-direction: column;\n  gap: 4px;\n  margin-bottom: 10px;\n}\n\n.hct-label {\n  font-size: 11px;\n  font-weight: 500;\n  color: var(--ui-text-secondary, #9ca3af);\n}\n\n.hct-input, .hct-select, .hct-textarea {\n  width: 100%;\n  padding: 6px 8px;\n  font-size: 12px;\n  border-radius: 4px;\n  border: 1px solid var(--ui-border, rgba(255, 255, 255, 0.15));\n  background: var(--ui-input-bg, rgba(0, 0, 0, 0.2));\n  color: var(--ui-text-primary, #fff);\n  outline: none;\n  font-family: inherit;\n}\n\n.hct-input:focus, .hct-select:focus, .hct-textarea:focus {\n  border-color: var(--ui-accent, #6366f1);\n}\n\n.hct-input:disabled, .hct-select:disabled, .hct-textarea:disabled {\n  opacity: 0.55;\n  cursor: not-allowed;\n  background: var(--ui-input-disabled-bg, rgba(255, 255, 255, 0.04));\n  border-color: var(--ui-border, rgba(255, 255, 255, 0.08));\n}\n\n.hct-checkbox-label {\n  display: inline-flex;\n  align-items: center;\n  gap: 6px;\n  cursor: pointer;\n  user-select: none;\n  font-size: 12px;\n  font-weight: 500;\n  color: var(--ui-text-primary, #fff);\n}\n\n.hct-code {\n  font-family: var(--font-mono, ui-monospace, SFMono-Regular, monospace);\n  font-size: 11px;\n  background: rgba(255, 255, 255, 0.06);\n  padding: 1px 4px;\n  border-radius: 3px;\n}\n\n.hct-team-config-scope {\n  margin-top: 6px;\n  padding-top: 6px;\n  border-top: 1px solid var(--ui-border, rgba(255, 255, 255, 0.06));\n  display: flex;\n  flex-direction: column;\n  gap: 3px;\n}\n\n.hct-textarea {\n  min-height: 54px;\n  resize: vertical;\n}\n\n/* \u6a21\u6001\u6846 / \u4e8c\u6b21\u786e\u8ba4 */\n.hct-modal-backdrop {\n  position: fixed;\n  inset: 0;\n  background: rgba(0, 0, 0, 0.65);\n  display: flex;\n  align-items: center;\n  justify-content: center;\n  z-index: 1000;\n  backdrop-filter: blur(2px);\n}\n\n.hct-modal {\n  background: var(--ui-panel-bg, #1e1e24);\n  border: 1px solid var(--ui-border, rgba(255, 255, 255, 0.15));\n  border-radius: 8px;\n  width: 90%;\n  max-width: 480px;\n  max-height: 85vh;\n  display: flex;\n  flex-direction: column;\n  overflow: hidden;\n  box-shadow: 0 16px 36px rgba(0, 0, 0, 0.5);\n}\n\n.hct-modal > form,\n.hct-modal form {\n  display: flex;\n  flex-direction: column;\n  min-height: 0;\n  flex: 1;\n  overflow: hidden;\n}\n\n.hct-modal-header {\n  padding: 10px 14px;\n  border-bottom: 1px solid var(--ui-border, rgba(255, 255, 255, 0.08));\n  display: flex;\n  align-items: center;\n  justify-content: space-between;\n  flex-shrink: 0;\n}\n\n.hct-modal-title {\n  font-size: 13px;\n  font-weight: 600;\n}\n\n.hct-modal-body {\n  padding: 14px;\n  overflow-y: auto;\n  font-size: 12px;\n  display: flex;\n  flex-direction: column;\n  gap: 10px;\n  min-height: 0;\n  flex: 1;\n}\n\n.hct-modal-footer {\n  padding: 10px 14px;\n  border-top: 1px solid var(--ui-border, rgba(255, 255, 255, 0.08));\n  display: flex;\n  align-items: center;\n  justify-content: flex-end;\n  gap: 8px;\n  background: rgba(255, 255, 255, 0.015);\n  flex-shrink: 0;\n}\n\n/* \u57df\u7edf\u8ba1\u805a\u5408\u6761\uff08\u8d85\u8fc715\u6761\u4efb\u52a1\u65f6\u805a\u5408\u5c55\u793a\uff09 */\n.hct-stats-bar {\n  display: flex;\n  gap: 8px;\n  flex-wrap: wrap;\n  padding: 8px 10px;\n  background: rgba(255, 255, 255, 0.02);\n  border-radius: 6px;\n  margin-bottom: 8px;\n  font-size: 11px;\n}\n\n.hct-stat-tag {\n  display: flex;\n  align-items: center;\n  gap: 4px;\n  padding: 2px 6px;\n  background: rgba(255, 255, 255, 0.04);\n  border-radius: 4px;\n}\n\n/* \u7a7a\u72b6\u6001 */\n.hct-empty-state {\n  display: flex;\n  flex-direction: column;\n  align-items: center;\n  justify-content: center;\n  padding: 32px 16px;\n  text-align: center;\n  gap: 10px;\n  color: var(--ui-text-secondary, #9ca3af);\n}\n\n.hct-empty-icon {\n  font-size: 28px;\n  opacity: 0.6;\n}\n\n.hct-empty-desc {\n  max-width: 320px;\n  font-size: 12px;\n  line-height: 1.5;\n}\n\n/* Outbox \u963b\u585e\u4e0e\u544a\u8b66 */\n.hct-outbox-alert {\n  border-left: 3px solid #ef4444;\n  background: rgba(239, 68, 68, 0.08);\n  padding: 8px 10px;\n  border-radius: 4px;\n  display: flex;\n  align-items: center;\n  justify-content: space-between;\n  font-size: 12px;\n}\n\n.hct-code-box {\n  background: rgba(0, 0, 0, 0.25);\n  padding: 6px 8px;\n  border-radius: 4px;\n  font-family: var(--font-mono, monospace);\n  font-size: 11px;\n  white-space: pre-wrap;\n  word-break: break-all;\n  max-height: 120px;\n  overflow-y: auto;\n}\n\n/* \u4efb\u52a1\u5217\u8868\u4e0e\u5361\u7247 */\n.hct-task-list {\n  display: flex;\n  flex-direction: column;\n  gap: 8px;\n}\n\n.hct-task-item {\n  background: var(--ui-card-bg, rgba(255, 255, 255, 0.02));\n  border: 1px solid var(--ui-border, rgba(255, 255, 255, 0.06));\n  border-radius: 6px;\n  overflow: hidden;\n  transition: all 0.15s ease;\n}\n\n.hct-task-item-header {\n  display: flex;\n  align-items: center;\n  justify-content: space-between;\n  padding: 8px 10px;\n  cursor: pointer;\n  background: rgba(255, 255, 255, 0.015);\n}\n\n.hct-task-item-header:hover {\n  background: rgba(255, 255, 255, 0.04);\n}\n\n.hct-task-item-body {\n  padding: 10px 12px;\n  border-top: 1px solid var(--ui-border, rgba(255, 255, 255, 0.05));\n  display: flex;\n  flex-direction: column;\n  gap: 8px;\n  font-size: 12px;\n}\n\n.hct-task-section {\n  display: flex;\n  flex-direction: column;\n  gap: 4px;\n}\n\n.hct-task-section-title {\n  font-size: 11px;\n  font-weight: 600;\n  color: var(--ui-text-secondary, #9ca3af);\n}\n"
const PLUGIN_ID = 'construction-team'
const ROUTE_PATH = '/construction-team'
const EVENT_NAME = 'plugin.construction-team.changed'
const POLL_INTERVAL_MS = 15000 // 15秒低频轮询（仅在页面可见时触发）

function makeRequestKey(prefix = 'req') {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

// 状态药丸组件
function StatusPill({ status }) {
  const norm = String(status || 'pending').toLowerCase()
  let label = norm
  let cls = 'hct-pill-unknown'

  if (['accepted', 'approved'].includes(norm)) {
    label = '已验收'
    cls = 'hct-pill-accepted'
  } else if (['completed', 'succeeded'].includes(norm)) {
    label = '执行完成待验'
    cls = 'hct-pill-completed'
  } else if (norm === 'unknown') {
    label = '未知需核对'
    cls = 'hct-pill-unknown'
  } else if (norm === 'needs_reconcile') {
    label = '待对账'
    cls = 'hct-pill-needs-reconcile'
  } else if (['interrupted', 'cancelled'].includes(norm)) {
    label = '中断/取消'
    cls = 'hct-pill-interrupted'
  } else if (['active'].includes(norm)) {
    label = '活跃'
    cls = 'hct-pill-active'
  } else if (['running'].includes(norm)) {
    label = '执行中'
    cls = 'hct-pill-running'
  } else if (['candidate', 'awaiting_review', 'review_pending'].includes(norm)) {
    label = '待验收'
    cls = 'hct-pill-candidate'
  } else if (['paused'].includes(norm)) {
    label = '已暂停'
    cls = 'hct-pill-paused'
  } else if (['stopped'].includes(norm)) {
    label = '已停止'
    cls = 'hct-pill-stopped'
  } else if (['failed', 'rejected'].includes(norm)) {
    label = '失败'
    cls = 'hct-pill-failed'
  } else if (['blocked'].includes(norm)) {
    label = '已阻塞'
    cls = 'hct-pill-blocked'
  } else if (['idle'].includes(norm)) {
    label = '空闲'
    cls = 'hct-pill-idle'
  } else if (['pending', 'dispatched'].includes(norm)) {
    label = '待处理'
    cls = 'hct-pill-pending'
  } else {
    label = norm
    cls = 'hct-pill-unknown'
  }

  return h('span', { className: `hct-pill ${cls}` }, label)
}

// 主工作区组件
function ConstructionTeamWorkspace({ ctx }) {
  const [teams, setTeams] = useState([])
  const [activeTeamId, setActiveTeamId] = useState('')
  const [snapshot, setSnapshot] = useState(null)
  const [settings, setSettings] = useState(null)
  const [loading, setLoading] = useState(false)
  const [actionPending, setActionPending] = useState(false)
  const [errorBanner, setErrorBanner] = useState(null)
  const [warningBanner, setWarningBanner] = useState(null)

  // 折叠状态记录
  const [expandedMembers, setExpandedMembers] = useState({})
  const [expandedTasks, setExpandedTasks] = useState({})
  const [isRootExpanded, setIsRootExpanded] = useState(true)

  // 会话打开意图 (window / tab)
  const [openSessionIntent, setOpenSessionIntent] = useState('window')

  // 模态框状态
  const [modalType, setModalType] = useState(null) // 'create_team' | 'add_member' | 'dispatch_task' | 'review' | 'stop_confirm' | 'member_message'
  const [modalTarget, setModalTarget] = useState(null)
  const [formMessageText, setFormMessageText] = useState('')

  // 表单状态
  const [formTeamName, setFormTeamName] = useState('')
  const [formTeamRoot, setFormTeamRoot] = useState('')
  const [formTeamCoordinatorModel, setFormTeamCoordinatorModel] = useState('')
  const [formTeamCoordinatorProvider, setFormTeamCoordinatorProvider] = useState('')
  const [formTeamSupervisorModel, setFormTeamSupervisorModel] = useState('')
  const [formTeamSupervisorProvider, setFormTeamSupervisorProvider] = useState('')
  const [formTeamWorkerModel, setFormTeamWorkerModel] = useState('')
  const [formTeamAdvisorEnabled, setFormTeamAdvisorEnabled] = useState(false)
  const [formTeamAdvisorModel, setFormTeamAdvisorModel] = useState('')
  const [formTeamAdvisorProvider, setFormTeamAdvisorProvider] = useState('')

  const [formMemberName, setFormMemberName] = useState('')
  const [formMemberRole, setFormMemberRole] = useState('supervisor')
  const [formMemberModel, setFormMemberModel] = useState('')
  const [formMemberProvider, setFormMemberProvider] = useState('')
  const [settingsLoadFailed, setSettingsLoadFailed] = useState(false)

  const [formTaskMemberId, setFormTaskMemberId] = useState('')
  const [formTaskTitle, setFormTaskTitle] = useState('')
  const [formTaskGoal, setFormTaskGoal] = useState('')
  const [formTaskAcceptance, setFormTaskAcceptance] = useState('')
  const [formTaskForbidden, setFormTaskForbidden] = useState('')
  const [formTaskDependsOn, setFormTaskDependsOn] = useState('')

  const [formReviewVerdict, setFormReviewVerdict] = useState('accept')
  const [formReviewEvidence, setFormReviewEvidence] = useState('')
  const [formReviewNote, setFormReviewNote] = useState('')

  const [formStopReason, setFormStopReason] = useState('')

  // 请求 Epoch 隔离与 Profile 切换检测
  const epochRef = useRef(0)
  // Context identity remains scoped to the active backend connection/Profile.
  const readOwner = () => `${host?.state?.connectionId?.get?.() || ''}:${host?.state?.profile?.get?.() || 'default'}`
  const initialProfile = readOwner()
  const [trackedProfile, setTrackedProfile] = useState(initialProfile)
  const requestKeys = useRef(new Map())
  const stableKey = (operation, payload) => {
    const fingerprint = `${operation}:${JSON.stringify(payload)}`
    if (!requestKeys.current.has(fingerprint)) requestKeys.current.set(fingerprint, makeRequestKey(operation))
    return requestKeys.current.get(fingerprint)
  }
  const clearRequestKeys = () => requestKeys.current.clear()
  const refreshRef = useRef(null)

  // 加载系统配置
  const loadSettings = useCallback(async () => {
    const reqEpoch = epochRef.current
    try {
      const data = await ctx.rest('/settings')
      if (epochRef.current !== reqEpoch) return
      if (data) {
        setSettings(data)
        setSettingsLoadFailed(false)
        const defaults = data.defaults || {}
        setFormTeamCoordinatorModel(value => value || defaults.coordinator_model || '')
        setFormTeamCoordinatorProvider(value => value || defaults.coordinator_provider || '')
        setFormTeamSupervisorModel(value => value || defaults.supervisor_model || '')
        setFormTeamSupervisorProvider(value => value || defaults.supervisor_provider || '')
        setFormTeamWorkerModel(value => value || defaults.worker_model || '')
        setFormTeamAdvisorModel(value => value || defaults.advisor_model || '')
        setFormTeamAdvisorProvider(value => value || defaults.advisor_provider || '')
      }
    } catch (err) {
      console.warn('[ConstructionTeam] loadSettings error:', err)
      if (epochRef.current === reqEpoch) {
        setSettings(null)
        setSettingsLoadFailed(true)
        setErrorBanner('模型配置读取失败: ' + (err.message || String(err)))
      }
    }
  }, [ctx])

  // 加载团队列表
  const loadTeams = useCallback(async () => {
    const reqEpoch = epochRef.current
    try {
      const data = await ctx.rest('/teams')
      if (epochRef.current !== reqEpoch) return
      const list = data?.teams || []
      setTeams(list)
      if (list.length > 0) {
        setActiveTeamId(prev => {
          if (prev && list.some(t => t.id === prev)) return prev
          return list[0].id
        })
      } else {
        setActiveTeamId('')
        setSnapshot(null)
      }
    } catch (err) {
      if (epochRef.current !== reqEpoch) return
      console.error('[ConstructionTeam] loadTeams error:', err)
      setErrorBanner('加载施工团队列表失败: ' + (err.message || String(err)))
    }
  }, [ctx])

  // 加载团队完整快照
  const loadSnapshot = useCallback(async (teamId) => {
    if (!teamId) {
      setSnapshot(null)
      return
    }
    const reqEpoch = epochRef.current
    setLoading(true)
    setErrorBanner(null)
    try {
      const snap = await ctx.rest('/teams/' + teamId)
      if (epochRef.current !== reqEpoch) return
      setSnapshot(snap)
      if (snap?.warnings && snap.warnings.length > 0) {
        setWarningBanner(snap.warnings.join('；'))
      } else {
        setWarningBanner(null)
      }
    } catch (err) {
      if (epochRef.current !== reqEpoch) return
      console.error('[ConstructionTeam] loadSnapshot error:', err)
      setErrorBanner('加载团队详情快照失败: ' + (err.message || String(err)))
    } finally {
      if (epochRef.current === reqEpoch) {
        setLoading(false)
      }
    }
  }, [ctx])


  // 提取可用候选模型与候选 Provider (供 datalist 自动补全，亦支持手动输入任意 ID)
  const availableModels = useMemo(() => {
    const set = new Set()
    if (Array.isArray(settings?.models)) {
      settings.models.forEach(m => {
        const id = typeof m === 'string' ? m : m?.model
        if (id) set.add(id)
      })
    }
    const def = settings?.defaults || {}
    if (def.coordinator_model) set.add(def.coordinator_model)
    if (def.supervisor_model) set.add(def.supervisor_model)
    if (def.worker_model) set.add(def.worker_model)
    if (def.advisor_model) set.add(def.advisor_model)
    return Array.from(set)
  }, [settings])

  const availableProviders = useMemo(() => {
    if (!settings?.providers) return []
    if (Array.isArray(settings.providers)) {
      return settings.providers
        .map(p => (typeof p === 'string' ? p : (p?.id || p?.name)))
        .filter(Boolean)
    }
    if (typeof settings.providers === 'object') {
      return Object.keys(settings.providers)
    }
    return []
  }, [settings])

  // 全量刷新
  const refreshAll = useCallback(async () => {
    await loadSettings()
    await loadTeams()
  }, [loadSettings, loadTeams])

  // 监听团队列表或活跃团队变化，加载快照
  useEffect(() => {
    if (activeTeamId) {
      loadSnapshot(activeTeamId)
    }
  }, [activeTeamId, loadSnapshot])

  // 轮询与事件监听生命周期 (15s 仅在页面可见时触发)
  useEffect(() => {
    refreshAll()

    const onVisibleTick = () => {
      if (typeof document !== 'undefined' && document.hidden) return
      refreshAll()
      if (activeTeamId) loadSnapshot(activeTeamId)
    }

    const unsubEvent = ctx?.onEvent
      ? ctx.onEvent(EVENT_NAME, onVisibleTick)
      : null

    const unsubInterval = ctx?.setInterval
      ? ctx.setInterval(onVisibleTick, POLL_INTERVAL_MS)
      : null

    return () => {
      if (typeof unsubEvent === 'function') unsubEvent()
      if (typeof unsubInterval === 'function') unsubInterval()
    }
  }, [ctx, activeTeamId, refreshAll, loadSnapshot])

  // Subscribe to SDK readonly atoms; reading .get() once is not a subscription.
  refreshRef.current = refreshAll
  useEffect(() => {
    const invalidate = () => {
      const owner = readOwner()
      if (owner === trackedProfile) return
      epochRef.current += 1
      setTrackedProfile(owner)
      setTeams([])
      setSnapshot(null)
      setSettings(null)
      setSettingsLoadFailed(false)
      setActiveTeamId('')
      setModalType(null)
      clearRequestKeys()
      // 清空表单草稿，避免不同 Profile 串旧数据
      setFormTeamName('')
      setFormTeamRoot('')
      setFormTeamCoordinatorModel('')
      setFormTeamCoordinatorProvider('')
      setFormTeamSupervisorModel('')
      setFormTeamSupervisorProvider('')
      setFormTeamWorkerModel('')
      setFormTeamAdvisorEnabled(false)
      setFormTeamAdvisorModel('')
      setFormTeamAdvisorProvider('')
      setFormMemberName('')
      setFormMemberRole('supervisor')
      setFormMemberModel('')
      setFormMemberProvider('')
      setFormTaskMemberId('')
      setFormTaskTitle('')
      setFormTaskGoal('')
      setFormTaskAcceptance('')
      setFormTaskForbidden('')
      setFormTaskDependsOn('')
      setFormReviewEvidence('')
      setFormReviewNote('')
      setFormStopReason('')
      setFormMessageText('')
      refreshRef.current?.()
    }
    const disposers = [host?.state?.profile, host?.state?.connectionId].map(atom => atom?.subscribe?.(invalidate)).filter(fn => typeof fn === 'function')
    const gateway = host?.state?.gateway
    const gatewayChanged = state => {
      if (typeof state === 'string' && state !== 'open') setErrorBanner(`网关状态：${state}，暂停界面操作`)
    }
    const unsubGateway = gateway?.subscribe?.(gatewayChanged)
    if (typeof unsubGateway === 'function') disposers.push(unsubGateway)
    return () => disposers.forEach(dispose => dispose())
  }, [trackedProfile])

  // 打开主管会话联动 (按需触发，不自动弹)
  const handleOpenSession = useCallback(async (sessionKey) => {
    if (!sessionKey) {
      setErrorBanner('该成员暂无可关联的有效会话密钥')
      return
    }
    if (host && typeof host.openSession === 'function') {
      try {
        await host.openSession(sessionKey, { intent: openSessionIntent || 'window' })
      } catch (err) {
        setErrorBanner('打开会话失败: ' + (err.message || String(err)))
      }
    } else {
      setErrorBanner('宿主环境当前不可用 host.openSession')
    }
  }, [openSessionIntent])

  // 团队控制操作 (pause, resume, recover)
  const handleControl = useCallback(async (action) => {
    if (!activeTeamId) return
    const reqEpoch = epochRef.current
    setActionPending(true)
    setErrorBanner(null)
    try {
      const snap = await ctx.rest('/teams/' + activeTeamId + '/control', {
        method: 'POST',
        body: { action }
      })
      if (epochRef.current !== reqEpoch) return
      if (snap) setSnapshot(snap)
      await loadTeams()
    } catch (err) {
      if (epochRef.current === reqEpoch) {
        setErrorBanner(`执行控制指令「${action}」失败: ` + (err.message || String(err)))
      }
    } finally {
      if (epochRef.current === reqEpoch) {
        setActionPending(false)
      }
    }
  }, [ctx, activeTeamId, loadTeams])

  // 停止团队二次确认执行 (严格限制本 team 范围，非全机停止)
  const handleConfirmStop = useCallback(async () => {
    if (!activeTeamId) return
    const reqEpoch = epochRef.current
    setActionPending(true)
    setErrorBanner(null)
    try {
      const snap = await ctx.rest('/teams/' + activeTeamId + '/control', {
        method: 'POST',
        body: {
          action: 'stop',
          reason: formStopReason.trim() || undefined
        }
      })
      if (epochRef.current !== reqEpoch) return
      if (snap) setSnapshot(snap)
      setModalType(null)
      setFormStopReason('')
      await loadTeams()
    } catch (err) {
      if (epochRef.current === reqEpoch) {
        setErrorBanner('停止团队失败: ' + (err.message || String(err)))
      }
    } finally {
      if (epochRef.current === reqEpoch) {
        setActionPending(false)
      }
    }
  }, [ctx, activeTeamId, formStopReason, loadTeams])

  // 创建团队
  const handleCreateTeamSubmit = useCallback(async (e) => {
    if (e && e.preventDefault) e.preventDefault()
    if (settingsLoadFailed || !settings) {
      setErrorBanner('模型配置读取失败，已禁止提交以防默认覆盖')
      return
    }
    if (!formTeamName.trim() || !formTeamRoot.trim()) {
      setErrorBanner('团队名称与工区根路径不能为空')
      return
    }

    const coordinatorModel = formTeamCoordinatorModel.trim() || settings?.defaults?.coordinator_model || 'gpt-6.1-sol'
    const supervisorModel = formTeamSupervisorModel.trim() || settings?.defaults?.supervisor_model || 'gpt-6.1-sol'
    const workerModel = formTeamWorkerModel.trim() || settings?.defaults?.worker_model || 'gemini-3.8-flash-high'

    if (formTeamAdvisorEnabled && !formTeamAdvisorModel.trim() && !settings?.defaults?.advisor_model) {
      setErrorBanner('顾问已启用时，顾问模型为必填项')
      return
    }

    const advisorModel = formTeamAdvisorEnabled
      ? (formTeamAdvisorModel.trim() || settings?.defaults?.advisor_model || null)
      : null
    const advisorProvider = formTeamAdvisorEnabled
      ? (formTeamAdvisorProvider.trim() || settings?.defaults?.advisor_provider || null)
      : null

    const reqEpoch = epochRef.current
    setActionPending(true)
    setErrorBanner(null)
    try {
      const snap = await ctx.rest('/teams', {
        method: 'POST',
        body: {
          name: formTeamName.trim(),
          root: formTeamRoot.trim(),
          request_key: stableKey('team_create', [
            formTeamName.trim(),
            formTeamRoot.trim(),
            coordinatorModel,
            formTeamCoordinatorProvider.trim() || null,
            supervisorModel,
            formTeamSupervisorProvider.trim() || null,
            workerModel,
            Boolean(formTeamAdvisorEnabled),
            advisorModel,
            advisorProvider
          ]),
          settings: {
            coordinator_model: coordinatorModel,
            coordinator_provider: formTeamCoordinatorProvider.trim() || null,
            supervisor_model: supervisorModel,
            supervisor_provider: formTeamSupervisorProvider.trim() || null,
            worker_model: workerModel,
            worker_provider: null,
            advisor_enabled: Boolean(formTeamAdvisorEnabled),
            advisor_model: advisorModel,
            advisor_provider: advisorProvider
          }
        }
      })
      if (epochRef.current !== reqEpoch) return
      setModalType(null)
      setFormTeamName('')
      setFormTeamRoot('')
      setFormTeamCoordinatorModel('')
      setFormTeamCoordinatorProvider('')
      setFormTeamSupervisorModel('')
      setFormTeamSupervisorProvider('')
      setFormTeamWorkerModel('')
      setFormTeamAdvisorEnabled(false)
      setFormTeamAdvisorModel('')
      setFormTeamAdvisorProvider('')
      await loadTeams()
      if (snap?.team?.id) {
        setActiveTeamId(snap.team.id)
        setSnapshot(snap)
      }
    } catch (err) {
      if (epochRef.current === reqEpoch) {
        setErrorBanner('创建团队失败: ' + (err.message || String(err)))
      }
    } finally {
      if (epochRef.current === reqEpoch) {
        setActionPending(false)
      }
    }
  }, [
    ctx,
    settingsLoadFailed,
    settings,
    formTeamName,
    formTeamRoot,
    formTeamCoordinatorModel,
    formTeamCoordinatorProvider,
    formTeamSupervisorModel,
    formTeamSupervisorProvider,
    formTeamWorkerModel,
    formTeamAdvisorEnabled,
    formTeamAdvisorModel,
    formTeamAdvisorProvider,
    loadTeams
  ])

  // 添加成员 (主管/顾问)
  const handleAddMemberSubmit = useCallback(async (e) => {
    if (e && e.preventDefault) e.preventDefault()
    if (!activeTeamId || !formMemberName.trim()) {
      setErrorBanner('成员名称不能为空')
      return
    }
    const role = formMemberRole || 'supervisor'
    const reqEpoch = epochRef.current
    setActionPending(true)
    setErrorBanner(null)
    try {
      const snap = await ctx.rest('/teams/' + activeTeamId + '/members', {
        method: 'POST',
        body: {
          name: formMemberName.trim(),
          role,
          model: formMemberModel.trim() || undefined,
          provider: formMemberProvider.trim() || undefined,
          request_key: stableKey(`member_add_${role}`, [
            activeTeamId,
            formMemberName.trim(),
            role,
            formMemberModel.trim(),
            formMemberProvider.trim()
          ])
        }
      })
      if (epochRef.current !== reqEpoch) return
      if (snap) setSnapshot(snap)
      setModalType(null)
      setFormMemberName('')
      setFormMemberRole('supervisor')
      setFormMemberModel('')
      setFormMemberProvider('')
    } catch (err) {
      if (epochRef.current === reqEpoch) {
        setErrorBanner('添加团队成员失败: ' + (err.message || String(err)))
      }
    } finally {
      if (epochRef.current === reqEpoch) {
        setActionPending(false)
      }
    }
  }, [
    ctx,
    activeTeamId,
    formMemberName,
    formMemberRole,
    formMemberModel,
    formMemberProvider
  ])

  // 派发任务 (acceptance, forbidden)
  const handleDispatchTaskSubmit = useCallback(async (e) => {
    if (e && e.preventDefault) e.preventDefault()
    if (!activeTeamId || !formTaskTitle.trim()) {
      setErrorBanner('任务标题不能为空')
      return
    }
    const reqEpoch = epochRef.current
    setActionPending(true)
    setErrorBanner(null)

    const acceptanceList = formTaskAcceptance
      .split('\n')
      .map(s => s.trim())
      .filter(Boolean)

    const forbiddenList = formTaskForbidden
      .split('\n')
      .map(s => s.trim())
      .filter(Boolean)

    const dependsOnList = formTaskDependsOn
      .split(/[\s,]+/)
      .map(s => s.trim())
      .filter(Boolean)

    try {
      const snap = await ctx.rest('/teams/' + activeTeamId + '/tasks', {
        method: 'POST',
        body: {
          member_id: formTaskMemberId || (snapshot?.members?.find(m => m.role !== 'advisor')?.id || snapshot?.members?.[0]?.id || ''),
          title: formTaskTitle.trim(),
          goal: formTaskGoal.trim() || formTaskTitle.trim(),
          acceptance: acceptanceList,
          forbidden: forbiddenList,
          depends_on: dependsOnList,
          request_key: stableKey('task_add', [activeTeamId, formTaskMemberId, formTaskTitle, formTaskGoal, formTaskAcceptance, formTaskForbidden, formTaskDependsOn])
        }
      })
      if (epochRef.current !== reqEpoch) return
      if (snap) setSnapshot(snap)
      setModalType(null)
      setFormTaskTitle('')
      setFormTaskGoal('')
      setFormTaskAcceptance('')
      setFormTaskForbidden('')
      setFormTaskDependsOn('')
    } catch (err) {
      if (epochRef.current === reqEpoch) {
        setErrorBanner('派发任务失败: ' + (err.message || String(err)))
      }
    } finally {
      if (epochRef.current === reqEpoch) {
        setActionPending(false)
      }
    }
  }, [ctx, activeTeamId, formTaskMemberId, formTaskTitle, formTaskGoal, formTaskAcceptance, formTaskForbidden, formTaskDependsOn, snapshot])

  // 任务验收/驳回评审 (verdict, evidence, note)
  const handleReviewSubmit = useCallback(async (e) => {
    if (e && e.preventDefault) e.preventDefault()
    if (!activeTeamId || !modalTarget) return
    const reqEpoch = epochRef.current
    setActionPending(true)
    setErrorBanner(null)

    const evidenceList = formReviewEvidence
      .split('\n')
      .map(s => s.trim())
      .filter(Boolean)

    try {
      const snap = await ctx.rest('/teams/' + activeTeamId + '/tasks/' + modalTarget.id + '/review', {
        method: 'POST',
        body: {
          verdict: formReviewVerdict, // backend verb: 'accept' | 'reject'
          evidence: evidenceList,
          note: formReviewNote.trim() || undefined,
          request_key: stableKey('review', [activeTeamId, modalTarget.id, formReviewVerdict, formReviewEvidence, formReviewNote])
        }
      })
      if (epochRef.current !== reqEpoch) return
      if (snap) setSnapshot(snap)
      setModalType(null)
      setModalTarget(null)
      setFormReviewEvidence('')
      setFormReviewNote('')
    } catch (err) {
      if (epochRef.current === reqEpoch) {
        setErrorBanner('任务评审提交失败: ' + (err.message || String(err)))
      }
    } finally {
      if (epochRef.current === reqEpoch) {
        setActionPending(false)
      }
    }
  }, [ctx, activeTeamId, modalTarget, formReviewVerdict, formReviewEvidence, formReviewNote])

  // 发送主管消息 / 纠偏指令 (running -> steer, idle -> message)
  const handleSendMessageSubmit = useCallback(async (e) => {
    if (e && e.preventDefault) e.preventDefault()
    if (!activeTeamId || !modalTarget || !formMessageText.trim()) {
      setErrorBanner('消息内容不能为空')
      return
    }
    const isRunning = modalTarget.status === 'running'
    const mode = isRunning ? 'steer' : 'message'
    const reqEpoch = epochRef.current
    setActionPending(true)
    setErrorBanner(null)
    try {
      const snap = await ctx.rest('/teams/' + activeTeamId + '/members/' + modalTarget.id + '/message', {
        method: 'POST',
        body: {
          text: formMessageText.trim(),
          mode: mode,
          request_key: stableKey('member_message', [activeTeamId, modalTarget.id, mode, formMessageText.trim()])
        }
      })
      if (epochRef.current !== reqEpoch) return
      if (snap) setSnapshot(snap)
      setModalType(null)
      setModalTarget(null)
      setFormMessageText('')
    } catch (err) {
      if (epochRef.current === reqEpoch) {
        setErrorBanner('发送主管消息/纠偏失败: ' + (err.message || String(err)))
      }
    } finally {
      if (epochRef.current === reqEpoch) {
        setActionPending(false)
      }
    }
  }, [ctx, activeTeamId, modalTarget, formMessageText])

  // 重试发件箱
  const handleRetryOutbox = useCallback(async () => {
    if (!activeTeamId) return
    const reqEpoch = epochRef.current
    setActionPending(true)
    setErrorBanner(null)
    try {
      const snap = await ctx.rest('/teams/' + activeTeamId + '/outbox/retry', {
        method: 'POST',
        body: { request_key: makeRequestKey('retry_outbox') }
      })
      if (epochRef.current !== reqEpoch) return
      if (snap) setSnapshot(snap)
    } catch (err) {
      if (epochRef.current === reqEpoch) {
        setErrorBanner('重试发件箱失败: ' + (err.message || String(err)))
      }
    } finally {
      if (epochRef.current === reqEpoch) {
        setActionPending(false)
      }
    }
  }, [ctx, activeTeamId])

  // 当前团队与各项聚合统计
  const activeTeam = snapshot?.team || teams.find(t => t.id === activeTeamId)
  const members = snapshot?.members || []
  const tasks = snapshot?.tasks || []
  const workers = snapshot?.workers || []
  const outbox = snapshot?.outbox || []

  // 任务统计 (若 >= 15 则按域或状态聚合)
  const taskStats = useMemo(() => {
    const byStatus = {}
    const byDomain = {}
    for (const t of tasks) {
      const st = t.status || 'pending'
      byStatus[st] = (byStatus[st] || 0) + 1
      const dom = t.domain || (t.member_id ? 'member:' + t.member_id.slice(0, 6) : 'default')
      byDomain[dom] = (byDomain[dom] || 0) + 1
    }
    return { byStatus, byDomain, total: tasks.length }
  }, [tasks])

  // 分离顾问 (Sidecar，只读无worker) 与主管 (Supervisors)
  const advisors = useMemo(() => members.filter(m => m.role === 'advisor'), [members])
  const supervisors = useMemo(() => members.filter(m => m.role !== 'advisor'), [members])

  // 将所有任务映射到对应主管分支（Supervisors），未明确指定则归属首个主管，无主管则归入 unassigned
  const { supervisorTasksMap, unassignedTasks } = useMemo(() => {
    const map = new Map()
    supervisors.forEach(s => map.set(s.id, []))
    const unassigned = []
    for (const t of tasks) {
      if (t.member_id && map.has(t.member_id)) {
        map.get(t.member_id).push(t)
      } else if (supervisors.length > 0) {
        map.get(supervisors[0].id).push(t)
      } else {
        unassigned.push(t)
      }
    }
    return { supervisorTasksMap: map, unassignedTasks: unassigned }
  }, [supervisors, tasks])

  // 可复用任务节点渲染 (保证 .hct-task-item 与 ID 定位，兼容所有既有测试)
  const renderTaskNode = useCallback((t, assignedMember) => {
    const isExpanded = expandedTasks[t.id] !== false
    const isCandidate = ['candidate', 'awaiting_review', 'review_pending'].includes(t.status)
    const memberName = assignedMember?.name || (members.find(m => m.id === t.member_id)?.name)

    return h(
      'div',
      { key: t.id, id: 'task-' + t.id, 'data-task-id': t.id, className: 'hct-task-item' },
      h(
        'div',
        {
          className: 'hct-task-item-header',
          onClick: () =>
            setExpandedTasks(prev => ({ ...prev, [t.id]: !isExpanded }))
        },
        h(
          'div',
          { style: { display: 'flex', alignItems: 'center', gap: 8 } },
          h('span', { style: { fontSize: 10 } }, isExpanded ? '▼' : '▶'),
          h('strong', { style: { fontSize: 13 } }, t.title),
          h(StatusPill, { status: t.status }),
          memberName &&
            h(
              'span',
              { style: { fontSize: 11, opacity: 0.7 } },
              `@${memberName}`
            )
        ),
        h(
          'div',
          { style: { display: 'flex', alignItems: 'center', gap: 6 } },
          isCandidate &&
            h(
              'button',
              {
                className: 'hct-btn hct-btn-xs hct-btn-primary',
                onClick: e => {
                  e.stopPropagation()
                  setModalTarget(t)
                  setFormReviewVerdict('accept')
                  setFormReviewEvidence(Array.isArray(t.evidence) ? t.evidence.join('\n') : (t.evidence || ''))
                  setModalType('review')
                }
              },
              '验收通过 ✓'
            ),
          isCandidate &&
            h(
              'button',
              {
                className: 'hct-btn hct-btn-xs hct-btn-danger',
                onClick: e => {
                  e.stopPropagation()
                  setModalTarget(t)
                  setFormReviewVerdict('reject')
                  setModalType('review')
                }
              },
              '驳回 ✗'
            )
        )
      ),
      // 折叠任务体
      isExpanded &&
        h(
          'div',
          { className: 'hct-task-item-body' },
          t.goal &&
            h(
              'div',
              { className: 'hct-task-section' },
              h('span', { className: 'hct-task-section-title' }, '🎯 目标:'),
              h('div', null, t.goal)
            ),
          t.acceptance && t.acceptance.length > 0 &&
            h(
              'div',
              { className: 'hct-task-section' },
              h('span', { className: 'hct-task-section-title' }, '🎯 验收标准:'),
              h(
                'ul',
                { style: { margin: 0, paddingLeft: 18 } },
                t.acceptance.map((a, idx) => h('li', { key: idx }, a))
              )
            ),
          t.forbidden && t.forbidden.length > 0 &&
            h(
              'div',
              { className: 'hct-task-section' },
              h('span', { className: 'hct-task-section-title' }, '🚫 禁止规则:'),
              h(
                'ul',
                { style: { margin: 0, paddingLeft: 18 } },
                t.forbidden.map((f, idx) => h('li', { key: idx }, f))
              )
            ),
          t.depends_on && t.depends_on.length > 0 &&
            h(
              'div',
              { className: 'hct-task-section' },
              h('span', { className: 'hct-task-section-title' }, '🔗 依赖任务:'),
              h('div', null, t.depends_on.join(', '))
            ),
          (t.evidence && (Array.isArray(t.evidence) ? t.evidence.length > 0 : Boolean(t.evidence))) &&
            h(
              'div',
              { className: 'hct-task-section' },
              h('span', { className: 'hct-task-section-title' }, '待主管/主脑验收证据:'),
              h(
                'div',
                { className: 'hct-code-box' },
                Array.isArray(t.evidence) ? t.evidence.join('\n') : String(t.evidence)
              )
            ),
          t.report &&
            h(
              'div',
              { className: 'hct-task-section' },
              h('span', { className: 'hct-task-section-title' }, '汇报总结:'),
              h('div', { className: 'hct-code-box' }, t.report)
            )
        )
    )
  }, [expandedTasks, members])

  return h(
    'div',
    { className: 'hct-root' },

    // 1. 顶部紧凑标题栏
    h(
      'header',
      { className: 'hct-header' },
      h(
        'div',
        { className: 'hct-header-left' },
        h('span', { className: 'hct-title-zh' }, '施工团队'),
        h('span', { className: 'hct-subtitle-en' }, 'hermes-construction-team'),
        loading && h('span', { style: { fontSize: 11, opacity: 0.6 } }, '加载中...')
      ),
      h(
        'div',
        { className: 'hct-header-actions' },
        h(
          'select',
          {
            className: 'hct-select',
            style: { width: 100, padding: '2px 6px', fontSize: 11 },
            value: openSessionIntent,
            onChange: e => setOpenSessionIntent(e.target.value),
            title: '主管会话打开模式'
          },
          h('option', { value: 'window' }, '窗口模式'),
          h('option', { value: 'tab' }, '标签页模式')
        ),
        h(
          'button',
          {
            className: 'hct-btn hct-btn-xs',
            onClick: () => {
              refreshAll()
              if (activeTeamId) loadSnapshot(activeTeamId)
            },
            title: '刷新团队状态'
          },
          '刷新'
        ),
        h(
          'button',
          {
            className: 'hct-btn hct-btn-xs hct-btn-primary',
            onClick: () => setModalType('create_team')
          },
          '+ 新建团队'
        )
      )
    ),

    // 2. 错误与警告条 (完全可见，不截断)
    errorBanner &&
      h(
        'div',
        { className: 'hct-banner hct-banner-error' },
        h('span', null, '⚠️ ' + errorBanner),
        h(
          'button',
          {
            className: 'hct-btn hct-btn-xs',
            onClick: () => setErrorBanner(null)
          },
          '关闭'
        )
      ),

    warningBanner &&
      h(
        'div',
        { className: 'hct-banner hct-banner-warning' },
        h('span', null, '⚡ ' + warningBanner),
        h(
          'button',
          {
            className: 'hct-btn hct-btn-xs',
            onClick: () => setWarningBanner(null)
          },
          '关闭'
        )
      ),

    // 3. 主界面双栏布局
    h(
      'main',
      { className: 'hct-main' },

      // 左侧栏：团队清单
      h(
        'aside',
        { className: 'hct-sidebar' },
        h(
          'div',
          {
            style: {
              padding: '8px 10px',
              borderBottom: '1px solid var(--ui-border, rgba(255,255,255,0.08))',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              fontSize: 11,
              fontWeight: 600
            }
          },
          h('span', null, '团队列表 (' + teams.length + ')'),
          teams.length > 0 &&
            h('span', { style: { color: 'var(--ui-text-tertiary, #9ca3af)', fontWeight: 400 } }, '单选展开')
        ),
        h(
          'div',
          { className: 'hct-team-list' },
          teams.length === 0
            ? h(
                'div',
                {
                  style: {
                    padding: '24px 12px',
                    textAlign: 'center',
                    color: 'var(--ui-text-tertiary, #9ca3af)',
                    fontSize: 12
                  }
                },
                '暂无团队'
              )
            : teams.map(t =>
                h(
                  'div',
                  {
                    key: t.id,
                    className: `hct-team-item ${t.id === activeTeamId ? 'hct-active' : ''}`,
                    onClick: () => setActiveTeamId(t.id)
                  },
                  h(
                    'div',
                    { className: 'hct-team-item-top' },
                    h('span', { className: 'hct-team-name' }, t.name),
                    h(StatusPill, { status: t.status })
                  ),
                  h(
                    'div',
                    { className: 'hct-team-item-meta' },
                    h(
                      'span',
                      {
                        style: {
                          maxWidth: 140,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap'
                        }
                      },
                      t.root || t.root_path || ''
                    ),
                    h('span', { style: { fontFamily: 'var(--font-mono, monospace)', fontSize: 10 } }, t.id.slice(0, 8))
                  )
                )
              )
        )
      ),

      // 右侧主内容区
      h(
        'div',
        { className: 'hct-content' },

        // 空态展示
        teams.length === 0 || !activeTeam
          ? h(
              'div',
              { className: 'hct-empty-state' },
              h('div', { className: 'hct-empty-icon' }, '🏗️'),
              h('div', { style: { fontSize: 14, fontWeight: 600 } }, '暂无活跃团队'),
              h(
                'div',
                { className: 'hct-empty-desc' },
                '未检测到已创建的施工团队。施工团队为独立工区执行多主管与多Worker协同构建，请通过右上角「+ 新建团队」创建或通过主脑派发指令创建。'
              ),
              h(
                'button',
                {
                  className: 'hct-btn hct-btn-primary',
                  onClick: () => setModalType('create_team')
                },
                '立即新建团队'
              )
            )
          : h(
              React.Fragment,
              null,

              // 3.1 团队控制栏与操作按钮
              h(
                'div',
                { className: 'hct-card' },
                h(
                  'div',
                  { className: 'hct-card-header' },
                  h(
                    'div',
                    { className: 'hct-card-title' },
                    h('span', null, '📋 ' + activeTeam.name),
                    h(StatusPill, { status: activeTeam.status }),
                    h(
                      'span',
                      {
                        style: {
                          fontSize: 11,
                          color: 'var(--ui-text-tertiary, #9ca3af)',
                          fontWeight: 400,
                          fontFamily: 'var(--font-mono, monospace)'
                        }
                      },
                      activeTeam.id
                    )
                  ),
                  h(
                    'div',
                    { style: { display: 'flex', gap: 6 } },
                    activeTeam.coordinator_key && h('button', {className:'hct-btn hct-btn-secondary hct-btn-xs', onClick:() => handleOpenSession(activeTeam.coordinator_key)}, '打开总控'),
                    activeTeam.status === 'active' &&
                      h(
                        'button',
                        {
                          className: 'hct-btn hct-btn-xs',
                          disabled: actionPending,
                          onClick: () => handleControl('pause')
                        },
                        '暂停团队'
                      ),
                    ['paused', 'stopped', 'needs_reconcile'].includes(activeTeam.status) &&
                      h(
                        'button',
                        {
                          className: 'hct-btn hct-btn-xs',
                          disabled: actionPending,
                          onClick: () => handleControl('resume')
                        },
                        '恢复团队'
                      ),
                    activeTeam.status !== 'stopped' &&
                      h(
                        'button',
                        {
                          className: 'hct-btn hct-btn-xs hct-btn-danger',
                          disabled: actionPending,
                          onClick: () => setModalType('stop_confirm')
                        },
                        '停止团队'
                      ),
                    h(
                      'button',
                      {
                        className: 'hct-btn hct-btn-xs',
                        disabled: actionPending,
                        onClick: () => handleControl('recover')
                      },
                      '现场核对'
                    ),
                    h(
                      'button',
                      {
                        className: 'hct-btn hct-btn-xs',
                        onClick: () => setModalType('add_member')
                      },
                      '+ 添加成员'
                    ),
                    h(
                      'button',
                      {
                        className: 'hct-btn hct-btn-xs hct-btn-primary',
                        onClick: () => {
                          setFormTaskMemberId(members[0]?.id || '')
                          setModalType('dispatch_task')
                        }
                      },
                      '+ 派发任务'
                    )
                  )
                ),
                h(
                  'div',
                  { className: 'hct-card-body', style: { fontSize: 12, display: 'flex', flexDirection: 'column', gap: 4 } },
                  h('div', null, h('strong', null, '工区根路径: '), activeTeam.root || activeTeam.root_path || '未指定'),
                  activeTeam.coordinator_key &&
                    h('div', null, h('strong', null, '协调主脑会话: '), activeTeam.coordinator_key),
                  h(
                    'div',
                    { className: 'hct-team-config-scope' },
                    h('div', { style: { fontSize: 11, fontWeight: 600, color: 'var(--ui-text-secondary, #9ca3af)', marginBottom: 2 } }, '本团队独立配置 (Scoped Settings):'),
                    h(
                      'div',
                      { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '4px 12px', fontSize: 11 } },
                      h('div', null, h('span', { style: { opacity: 0.75 } }, '总控: '), h('span', { className: 'hct-code' }, activeTeam.settings?.coordinator_model || '默认'), activeTeam.settings?.coordinator_provider ? h('span', { style: { opacity: 0.6 } }, ' (' + activeTeam.settings.coordinator_provider + ')') : null),
                      h('div', null, h('span', { style: { opacity: 0.75 } }, '主管: '), h('span', { className: 'hct-code' }, activeTeam.settings?.supervisor_model || '默认'), activeTeam.settings?.supervisor_provider ? h('span', { style: { opacity: 0.6 } }, ' (' + activeTeam.settings.supervisor_provider + ')') : null),
                      h('div', null, h('span', { style: { opacity: 0.75 } }, '工人: '), h('span', { className: 'hct-code' }, activeTeam.settings?.worker_model || '默认'), h('span', { style: { opacity: 0.6 } }, ' (继承对应主管 Provider)')),
                      h('div', null, h('span', { style: { opacity: 0.75 } }, '顾问: '), activeTeam.settings?.advisor_enabled ? [h('span', { key: 'm', className: 'hct-code' }, activeTeam.settings?.advisor_model || '默认'), activeTeam.settings?.advisor_provider ? h('span', { key: 'p', style: { opacity: 0.6 } }, ' (' + activeTeam.settings.advisor_provider + ')') : null] : h('span', { style: { opacity: 0.5 } }, '未启用'))
                    )
                  )
                )
              ),

              // 3.2 发件箱告警与阻塞重试
              outbox.length > 0 &&
                h(
                  'div',
                  { className: 'hct-outbox-alert' },
                  h(
                    'span',
                    null,
                    `发件箱存在 ${outbox.length} 条阻断/失败消息: ${outbox.map(o => `#${o.id}`).join(', ')}`
                  ),
                  h(
                    'div',
                    { style: { display: 'flex', gap: 6 } },
                    outbox.map(o =>
                      h(
                        'button',
                        {
                          key: o.id,
                          className: 'hct-btn hct-btn-xs hct-btn-danger',
                          disabled: actionPending,
                          onClick: handleRetryOutbox
                        },
                        `重试 #${o.id}`
                      )
                    )
                  )
                ),

                            // 3.3 团队总控协作树与分层架构
              h(
                'div',
                { className: 'hct-card' },
                h(
                  'div',
                  { className: 'hct-card-header' },
                  h('div', { className: 'hct-card-title' }, `🌿 团队总控与分层架构 (主管:${supervisors.length} / 顾问:${advisors.length} / 任务:${tasks.length})`),
                  h(
                    'div',
                    { style: { display: 'flex', gap: 6 } },
                    h(
                      'button',
                      {
                        className: 'hct-btn hct-btn-xs',
                        onClick: () => setModalType('add_member')
                      },
                      '+ 添加成员'
                    ),
                    h(
                      'button',
                      {
                        className: 'hct-btn hct-btn-xs hct-btn-primary',
                        onClick: () => {
                          setFormTaskMemberId(supervisors[0]?.id || members[0]?.id || '')
                          setModalType('dispatch_task')
                        }
                      },
                      '+ 派发任务'
                    )
                  )
                ),
                h(
                  'div',
                  { className: 'hct-card-body' },

                  // 超过 15 条任务时的域分布聚合条
                  tasks.length >= 15 &&
                    h(
                      'div',
                      { className: 'hct-stats-bar' },
                      h('strong', null, '域分布统计: '),
                      Object.entries(taskStats.byDomain).map(([dom, cnt]) =>
                        h('span', { key: dom, className: 'hct-stat-tag' }, `${dom}: ${cnt}`)
                      ),
                      h('span', { style: { marginLeft: 8 } }, '|'),
                      Object.entries(taskStats.byStatus).map(([st, cnt]) =>
                        h('span', { key: st, className: 'hct-stat-tag' }, `${st}: ${cnt}`)
                      )
                    ),

                  // 统一总控协作树 (.hct-tree)
                  h(
                    'div',
                    { className: 'hct-tree' },
                    // 第一级总控 Root (.hct-tree-root)
                    h(
                      'div',
                      { className: 'hct-tree-root' },
                      h(
                        'div',
                        {
                          className: 'hct-tree-root-header',
                          onClick: () => setIsRootExpanded(prev => !prev),
                          style: { cursor: 'pointer' }
                        },
                        h(
                          'div',
                          { style: { display: 'flex', alignItems: 'center', gap: 8 } },
                          h('span', { style: { fontSize: 10 } }, isRootExpanded ? '▼' : '▶'),
                          h('strong', { style: { fontSize: 13 } }, `🎯 总控 (Coordinator): ${activeTeam.name}`),
                          h(StatusPill, { status: activeTeam.status }),
                          activeTeam.coordinator_key &&
                            h(
                              'span',
                              { style: { fontSize: 11, color: 'var(--ui-text-tertiary, #9ca3af)', fontFamily: 'var(--font-mono, monospace)' } },
                              `key:${activeTeam.coordinator_key}`
                            )
                        ),
                        h(
                          'div',
                          { style: { display: 'flex', alignItems: 'center', gap: 6 } },
                          activeTeam.coordinator_key &&
                            h(
                              'button',
                              {
                                className: 'hct-btn hct-btn-xs',
                                onClick: e => {
                                  e.stopPropagation()
                                  handleOpenSession(activeTeam.coordinator_key)
                                },
                                title: '打开总控交互会话'
                              },
                              '打开总控 ↗'
                            )
                        )
                      ),
                      isRootExpanded &&
                        h(
                          'div',
                          { className: 'hct-tree-root-body' },
                          // 顾问 Sidecar (独立提示只读无 worker)
                          advisors.length > 0 &&
                            h(
                              'div',
                              { className: 'hct-advisor-sidecar' },
                              h('div', { style: { fontSize: 11, fontWeight: 600, color: '#c084fc' } }, '💡 旁路顾问 (Advisor - 只读咨询，无下属 Worker)'),
                              advisors.map(adv =>
                                h(
                                  'div',
                                  { key: adv.id, className: 'hct-advisor-card' },
                                  h(
                                    'div',
                                    { style: { display: 'flex', alignItems: 'center', gap: 6 } },
                                    h('strong', null, adv.name),
                                    h('span', { className: 'hct-badge-advisor' }, '顾问'),
                                    h(StatusPill, { status: adv.status }),
                                    adv.model &&
                                      h('span', { style: { fontSize: 10, opacity: 0.7, fontFamily: 'var(--font-mono, monospace)' } }, adv.model)
                                  ),
                                  h(
                                    'div',
                                    { style: { display: 'flex', alignItems: 'center', gap: 6 } },
                                    adv.session_key &&
                                      h(
                                        'button',
                                        {
                                          className: 'hct-btn hct-btn-xs',
                                          onClick: () => handleOpenSession(adv.session_key),
                                          title: '打开顾问会话'
                                        },
                                        '打开顾问 ↗'
                                      )
                                  )
                                )
                              )
                            ),
                          // 第二级主管 (.supervisors)
                          h(
                            'div',
                            { className: 'supervisors hct-supervisors' },
                            supervisors.length === 0
                              ? h('div', { style: { color: 'var(--ui-text-tertiary, #9ca3af)', fontSize: 12, padding: '4px 0' } }, '暂无主管，点击上方「+ 添加成员」指派主管')
                              : supervisors.map(m => {
                                  const isExpanded = expandedMembers[m.id] !== false
                                  const memberWorkers = workers.filter(w => w.member_id === m.id)
                                  const memberTasks = supervisorTasksMap.get(m.id) || []
                                  return h(
                                    'div',
                                    { key: m.id, className: 'hct-tree-node' },
                                    h(
                                      'div',
                                      { className: 'hct-tree-header' },
                                      h(
                                        'div',
                                        {
                                          style: { display: 'flex', alignItems: 'center', gap: 8 },
                                          onClick: () => setExpandedMembers(prev => ({ ...prev, [m.id]: !isExpanded }))
                                        },
                                        h('span', { style: { fontSize: 10 } }, isExpanded ? '▼' : '▶'),
                                        h('strong', { style: { fontSize: 13 } }, m.name),
                                        h('span', { style: { fontSize: 11, opacity: 0.7 } }, `[${m.role || 'supervisor'}]`),
                                        h(StatusPill, { status: m.status }),
                                        m.model &&
                                          h(
                                            'span',
                                            { style: { fontSize: 11, color: 'var(--ui-text-tertiary, #9ca3af)', fontFamily: 'var(--font-mono, monospace)' } },
                                            `${m.model}${m.provider ? ' (' + m.provider + ')' : ''}`
                                          )
                                      ),
                                      h(
                                        'div',
                                        { style: { display: 'flex', alignItems: 'center', gap: 6 } },
                                        h(
                                          'button',
                                          {
                                            className: 'hct-btn hct-btn-xs',
                                            onClick: e => {
                                              e.stopPropagation()
                                              setModalTarget(m)
                                              setFormMessageText('')
                                              setModalType('member_message')
                                            },
                                            title: m.status === 'running' ? '向运行中主管发送纠偏指令 (steer)' : '向主管发送工作消息 (message)'
                                          },
                                          m.status === 'running' ? '纠偏 ⚡' : '发消息 ✉'
                                        ),
                                        m.session_key &&
                                          h(
                                            'button',
                                            {
                                              className: 'hct-btn hct-btn-xs',
                                              onClick: e => {
                                                e.stopPropagation()
                                                handleOpenSession(m.session_key)
                                              },
                                              title: '打开主管交互会话'
                                            },
                                            '打开主管 ↗'
                                          )
                                      )
                                    ),
                                    // 展开主管分支 (下属 Workers 与 关联 Tasks)
                                    isExpanded &&
                                      h(
                                        'div',
                                        { className: 'hct-tree-branch' },
                                        // 第三级：下属 Workers
                                        h(
                                          'div',
                                          { className: 'hct-worker-list' },
                                          memberWorkers.length === 0
                                            ? h('div', { style: { fontSize: 11, opacity: 0.6, padding: '2px 8px' } }, '暂无下属 Worker 运行')
                                            : memberWorkers.map(w =>
                                                h(
                                                  'div',
                                                  { key: w.id, className: 'hct-worker-card' },
                                                  h(
                                                    'div',
                                                    { style: { display: 'flex', alignItems: 'center', gap: 6 } },
                                                    h('span', null, '⚙️'),
                                                    h('span', { style: { fontWeight: 500 } }, w.name || w.id),
                                                    h('span', { style: { fontSize: 10, opacity: 0.7 } }, `[${w.mode || 'read'}]`),
                                                    h(StatusPill, { status: w.status }),
                                                    w.actual_model &&
                                                      h(
                                                        'span',
                                                        { style: { fontSize: 10, opacity: 0.7, fontFamily: 'var(--font-mono, monospace)' } },
                                                        w.actual_model
                                                      )
                                                  ),
                                                  w.error &&
                                                    h(
                                                      'div',
                                                      { style: { color: '#f87171', fontSize: 11 } },
                                                      '⚠️ Worker 异常: ' + w.error
                                                    )
                                                )
                                              )
                                        ),
                                        // 关联 Tasks (不截断)
                                        memberTasks.length > 0 &&
                                          h(
                                            'div',
                                            { className: 'hct-task-list', style: { marginTop: 4 } },
                                            memberTasks.map(t => renderTaskNode(t, m))
                                          )
                                      )
                                  )
                                })
                          ),
                          // 无主管归属任务 (例如未派发给主管的任务)
                          unassignedTasks.length > 0 &&
                            h(
                              'div',
                              { className: 'hct-task-list', style: { marginTop: 8 } },
                              unassignedTasks.map(t => renderTaskNode(t))
                            )
                        )
                    )
                  )
                )
              )
            )
      )
    ),

    // 4. 模态对话框

    // 4.1 新建团队模态框
    modalType === 'create_team' &&
      h(
        'div',
        { className: 'hct-modal-backdrop' },
        h(
          'div',
          { className: 'hct-modal' },
          h('div', { className: 'hct-modal-header' }, h('span', { className: 'hct-modal-title' }, '新建施工团队')),
          h(
            'form',
            { onSubmit: handleCreateTeamSubmit },
            h(
              'div',
              { className: 'hct-modal-body' },
              h(
                'div',
                { className: 'hct-form-group' },
                h('label', { className: 'hct-label' }, '团队名称'),
                h('input', {
                  className: 'hct-input',
                  placeholder: '例如: 前端重构施工团队',
                  value: formTeamName,
                  onChange: e => setFormTeamName(e.target.value)
                })
              ),
              h(
                'div',
                { className: 'hct-form-group' },
                h('label', { className: 'hct-label' }, '工区根路径 (root)'),
                h('input', {
                  className: 'hct-input',
                  placeholder: '例如: ~/projects/tools/my-app',
                  value: formTeamRoot,
                  onChange: e => setFormTeamRoot(e.target.value)
                })
              ),
              h(
                'div',
                { className: 'hct-form-group' },
                h('label', { className: 'hct-label' }, '总控模型 (Coordinator Model)'),
                h('input', {
                  className: 'hct-input',
                  list: 'hct-models-datalist',
                  placeholder: settings?.defaults?.coordinator_model || '例如: gpt-6.1-sol',
                  value: formTeamCoordinatorModel,
                  onChange: e => setFormTeamCoordinatorModel(e.target.value)
                })
              ),
              h(
                'div',
                { className: 'hct-form-group' },
                h('label', { className: 'hct-label' }, '总控 Provider (可选)'),
                h('input', {
                  className: 'hct-input',
                  list: 'hct-providers-datalist',
                  placeholder: settings?.defaults?.coordinator_provider || '留空沿用 Profile / 宿主默认',
                  value: formTeamCoordinatorProvider,
                  onChange: e => setFormTeamCoordinatorProvider(e.target.value)
                })
              ),
              h(
                'div',
                { className: 'hct-form-group' },
                h('label', { className: 'hct-label' }, '主管模型 (Supervisor Model)'),
                h('input', {
                  className: 'hct-input',
                  list: 'hct-models-datalist',
                  placeholder: settings?.defaults?.supervisor_model || '例如: gpt-6.1-sol',
                  value: formTeamSupervisorModel,
                  onChange: e => setFormTeamSupervisorModel(e.target.value)
                })
              ),
              h(
                'div',
                { className: 'hct-form-group' },
                h('label', { className: 'hct-label' }, '主管 Provider (可选)'),
                h('input', {
                  className: 'hct-input',
                  list: 'hct-providers-datalist',
                  placeholder: settings?.defaults?.supervisor_provider || '留空沿用 Profile / 宿主默认',
                  value: formTeamSupervisorProvider,
                  onChange: e => setFormTeamSupervisorProvider(e.target.value)
                })
              ),
              h(
                'div',
                { className: 'hct-form-group' },
                h('label', { className: 'hct-label' }, '工人模型 (Worker Model)'),
                h('input', {
                  className: 'hct-input',
                  list: 'hct-models-datalist',
                  placeholder: settings?.defaults?.worker_model || '例如: gemini-3.8-flash-high',
                  value: formTeamWorkerModel,
                  onChange: e => setFormTeamWorkerModel(e.target.value)
                })
              ),
              h(
                'div',
                { className: 'hct-form-group' },
                h('label', { className: 'hct-label' }, '工人 Provider 路由'),
                h('input', {
                  className: 'hct-input',
                  readOnly: true,
                  disabled: true,
                  value: '工人模型可独立选择，Provider继承对应主管'
                }),
                h('div', { style: { fontSize: 11, opacity: 0.65, marginTop: 2 } }, '工人模型可独立选择，Provider继承对应主管')
              ),
              h(
                'div',
                { className: 'hct-form-group', style: { borderTop: '1px solid var(--ui-border, rgba(255, 255, 255, 0.08))', paddingTop: 8, marginTop: 6 } },
                h(
                  'label',
                  { className: 'hct-checkbox-label' },
                  h('input', {
                    type: 'checkbox',
                    checked: formTeamAdvisorEnabled,
                    onChange: e => setFormTeamAdvisorEnabled(e.target.checked)
                  }),
                  '启用顾问旁路 (Advisor)'
                )
              ),
              h(
                'div',
                { className: 'hct-form-group' },
                h('label', { className: 'hct-label' }, formTeamAdvisorEnabled ? '顾问模型 (Advisor Model) *必填' : '顾问模型 (Advisor Model) - 未启用'),
                h('input', {
                  className: 'hct-input',
                  list: 'hct-models-datalist',
                  disabled: !formTeamAdvisorEnabled,
                  required: formTeamAdvisorEnabled,
                  placeholder: formTeamAdvisorEnabled ? (settings?.defaults?.advisor_model || '例如: gpt-6.1-sol') : '未启用顾问',
                  value: formTeamAdvisorModel,
                  onChange: e => setFormTeamAdvisorModel(e.target.value)
                })
              ),
              h(
                'div',
                { className: 'hct-form-group' },
                h('label', { className: 'hct-label' }, '顾问 Provider (可选)'),
                h('input', {
                  className: 'hct-input',
                  list: 'hct-providers-datalist',
                  disabled: !formTeamAdvisorEnabled,
                  placeholder: formTeamAdvisorEnabled ? (settings?.defaults?.advisor_provider || '留空沿用 Profile / 宿主默认') : '未启用顾问',
                  value: formTeamAdvisorProvider,
                  onChange: e => setFormTeamAdvisorProvider(e.target.value)
                })
              ),
              h(
                'div',
                { style: { fontSize: 11, opacity: 0.7, marginTop: 4, lineHeight: 1.4 } },
                '💡 独立模型选择：总控、主管、工人与顾问每级模型完全独立；支持从已配置目录补全或手动输入任意有效模型 ID（非固定枚举）；工人 Provider 继承对应主管。仅保存本团队配置，不修改全局。'
              )
            ),
            h(
              'div',
              { className: 'hct-modal-footer' },
              h(
                'button',
                {
                  type: 'button',
                  className: 'hct-btn',
                  onClick: () => setModalType(null)
                },
                '取消'
              ),
              h(
                'button',
                {
                  type: 'submit',
                  className: 'hct-btn hct-btn-primary',
                  disabled: actionPending || settingsLoadFailed || !settings,
                  onClick: handleCreateTeamSubmit
                },
                '立即创建'
              )
            )
          )
        )
      ),

    // 4.2 添加成员模态框
    modalType === 'add_member' &&
      h(
        'div',
        { className: 'hct-modal-backdrop' },
        h(
          'div',
          { className: 'hct-modal' },
          h('div', { className: 'hct-modal-header' }, h('span', { className: 'hct-modal-title' }, '添加团队成员 (主管/顾问)')),
          h(
            'form',
            { onSubmit: handleAddMemberSubmit },
            h(
              'div',
              { className: 'hct-modal-body' },
              h(
                'div',
                { className: 'hct-form-group' },
                h('label', { className: 'hct-label' }, '成员名称'),
                h('input', {
                  className: 'hct-input',
                  placeholder: '例如: 前端架构主管',
                  value: formMemberName,
                  onChange: e => setFormMemberName(e.target.value)
                })
              ),
              h(
                'div',
                { className: 'hct-form-group' },
                h('label', { className: 'hct-label' }, '角色'),
                h(
                  'select',
                  {
                    className: 'hct-select',
                    value: formMemberRole,
                    onChange: e => setFormMemberRole(e.target.value)
                  },
                  h('option', { value: 'supervisor' }, '主管 (Supervisor)'),
                  h('option', { value: 'advisor' }, '顾问 (Advisor)')
                )
              ),
              (() => {
                const isAdvisor = formMemberRole === 'advisor'
                const roleDefaultModel = isAdvisor
                  ? (activeTeam?.settings?.advisor_model || settings?.defaults?.advisor_model || '')
                  : (activeTeam?.settings?.supervisor_model || settings?.defaults?.supervisor_model || 'gpt-6.1-sol')
                const roleDefaultProvider = isAdvisor
                  ? (activeTeam?.settings?.advisor_provider || settings?.defaults?.advisor_provider || '')
                  : (activeTeam?.settings?.supervisor_provider || settings?.defaults?.supervisor_provider || '')
                return h(
                  Fragment,
                  null,
                  h(
                    'div',
                    { className: 'hct-form-group' },
                    h('label', { className: 'hct-label' }, '指定模型 (可选 - 留空继承' + (isAdvisor ? '顾问' : '主管') + '默认)'),
                    h('input', {
                      className: 'hct-input',
                      list: 'hct-models-datalist',
                      placeholder: roleDefaultModel ? ('继承默认: ' + roleDefaultModel) : '未指定模型',
                      value: formMemberModel,
                      onChange: e => setFormMemberModel(e.target.value)
                    })
                  ),
                  h(
                    'div',
                    { className: 'hct-form-group' },
                    h('label', { className: 'hct-label' }, '提供商 (可选 - 留空继承' + (isAdvisor ? '顾问' : '主管') + '默认)'),
                    h('input', {
                      className: 'hct-input',
                      list: 'hct-providers-datalist',
                      placeholder: roleDefaultProvider ? ('继承默认: ' + roleDefaultProvider) : '沿用宿主/Profile 默认',
                      value: formMemberProvider,
                      onChange: e => setFormMemberProvider(e.target.value)
                    })
                  ),
                  h(
                    'div',
                    { style: { fontSize: 11, opacity: 0.65, lineHeight: 1.4 } },
                    isAdvisor
                      ? (activeTeam?.settings?.advisor_enabled
                          ? ('顾问默认模型: ' + (roleDefaultModel || '未配置') + '；可输入独立模型进行覆盖。')
                          : '提示：本团队未启用顾问旁路，直接添加可能被后端校验拒绝。')
                      : ('主管默认模型: ' + (roleDefaultModel || '未配置') + '；可输入独立模型进行覆盖。')
                  )
                )
              })()
            ),
            h(
              'div',
              { className: 'hct-modal-footer' },
              h(
                'button',
                {
                  type: 'button',
                  className: 'hct-btn',
                  onClick: () => setModalType(null)
                },
                '取消'
              ),
              h(
                'button',
                {
                  type: 'submit',
                  className: 'hct-btn hct-btn-primary',
                  disabled: actionPending,
                  onClick: handleAddMemberSubmit
                },
                '确认添加'
              )
            )
          )
        )
      ),

    // 4.3 派发任务模态框
    modalType === 'dispatch_task' &&
      h(
        'div',
        { className: 'hct-modal-backdrop' },
        h(
          'div',
          { className: 'hct-modal' },
          h('div', { className: 'hct-modal-header' }, h('span', { className: 'hct-modal-title' }, '派发新任务')),
          h(
            'form',
            { onSubmit: handleDispatchTaskSubmit },
            h(
              'div',
              { className: 'hct-modal-body' },
              h(
                'div',
                { className: 'hct-form-group' },
                h('label', { className: 'hct-label' }, '指派主管 (member_id)'),
                h(
                  'select',
                  {
                    className: 'hct-select',
                    value: formTaskMemberId,
                    onChange: e => setFormTaskMemberId(e.target.value)
                  },
                  members.map(m => h('option', { key: m.id, value: m.id }, `${m.name} (${m.role})`))
                )
              ),
              h(
                'div',
                { className: 'hct-form-group' },
                h('label', { className: 'hct-label' }, '任务标题'),
                h('input', {
                  className: 'hct-input',
                  placeholder: '例如: 修正前端JSON契约与无缝对接',
                  value: formTaskTitle,
                  onChange: e => setFormTaskTitle(e.target.value)
                })
              ),
              h(
                'div',
                { className: 'hct-form-group' },
                h('label', { className: 'hct-label' }, '任务目标 (goal)'),
                h('textarea', {
                  className: 'hct-textarea',
                  placeholder: '详细阐述任务执行目标...',
                  value: formTaskGoal,
                  onChange: e => setFormTaskGoal(e.target.value)
                })
              ),
              h(
                'div',
                { className: 'hct-form-group' },
                h('label', { className: 'hct-label' }, '验收标准 (每行一条)'),
                h('textarea', {
                  className: 'hct-textarea',
                  placeholder: '例如:\n13单元测试全绿\n无跨域/无mock数据报错',
                  value: formTaskAcceptance,
                  onChange: e => setFormTaskAcceptance(e.target.value)
                })
              ),
              h(
                'div',
                { className: 'hct-form-group' },
                h('label', { className: 'hct-label' }, '禁止规则 (每行一条)'),
                h('textarea', {
                  className: 'hct-textarea',
                  placeholder: '例如:\n禁止外部CDN\n禁止全机停止',
                  value: formTaskForbidden,
                  onChange: e => setFormTaskForbidden(e.target.value)
                })
              ),
              h(
                'div',
                { className: 'hct-form-group' },
                h('label', { className: 'hct-label' }, '依赖任务 (空格或逗号分隔)'),
                h('input', {
                  className: 'hct-input',
                  placeholder: '例如: t_01, t_02',
                  value: formTaskDependsOn,
                  onChange: e => setFormTaskDependsOn(e.target.value)
                })
              )
            ),
            h(
              'div',
              { className: 'hct-modal-footer' },
              h(
                'button',
                {
                  type: 'button',
                  className: 'hct-btn',
                  onClick: () => setModalType(null)
                },
                '取消'
              ),
              h(
                'button',
                {
                  type: 'submit',
                  className: 'hct-btn hct-btn-primary',
                  disabled: actionPending,
                  onClick: handleDispatchTaskSubmit
                },
                '确认派发'
              )
            )
          )
        )
      ),

    // 4.4 验收与驳回评审模态框
    modalType === 'review' &&
      modalTarget &&
      h(
        'div',
        { className: 'hct-modal-backdrop' },
        h(
          'div',
          { className: 'hct-modal' },
          h(
            'div',
            { className: 'hct-modal-header' },
            h('span', { className: 'hct-modal-title' }, `任务验收评审: ${modalTarget.title}`)
          ),
          h(
            'form',
            { onSubmit: handleReviewSubmit },
            h(
              'div',
              { className: 'hct-modal-body' },
              h(
                'div',
                { className: 'hct-form-group' },
                h('label', { className: 'hct-label' }, '评审裁决 (Verdict)'),
                h(
                  'select',
                  {
                    className: 'hct-select',
                    value: formReviewVerdict,
                    onChange: e => setFormReviewVerdict(e.target.value)
                  },
                  h('option', { value: 'accept' }, '验收通过 (accept)'),
                  h('option', { value: 'reject' }, '驳回重做 (reject)')
                )
              ),
              h(
                'div',
                { className: 'hct-form-group' },
                h('label', { className: 'hct-label' }, '审核证据 (Evidence 每行一条)'),
                h('textarea', {
                  className: 'hct-textarea',
                  placeholder: '记录代码差异、测试日志或验收证据...',
                  value: formReviewEvidence,
                  onChange: e => setFormReviewEvidence(e.target.value)
                })
              ),
              h(
                'div',
                { className: 'hct-form-group' },
                h('label', { className: 'hct-label' }, '评审意见 (Note)'),
                h('textarea', {
                  className: 'hct-textarea',
                  placeholder: '评审理由或改进指导...',
                  value: formReviewNote,
                  onChange: e => setFormReviewNote(e.target.value)
                })
              )
            ),
            h(
              'div',
              { className: 'hct-modal-footer' },
              h(
                'button',
                {
                  type: 'button',
                  className: 'hct-btn',
                  onClick: () => {
                    setModalType(null)
                    setModalTarget(null)
                  }
                },
                '取消'
              ),
              h(
                'button',
                {
                  type: 'submit',
                  className: `hct-btn ${formReviewVerdict === 'accept' ? 'hct-btn-primary' : 'hct-btn-danger'}`,
                  disabled: actionPending || (formReviewVerdict === 'accept' ? !formReviewEvidence.trim() : !formReviewNote.trim()),
                  onClick: handleReviewSubmit
                },
                formReviewVerdict === 'accept' ? '确认通过' : '确认驳回'
              )
            )
          )
        )
      ),

    // 4.5 停止团队二次确认对话框 (严格限制本 team 范围，非全机停止)
    modalType === 'stop_confirm' &&
      h(
        'div',
        { className: 'hct-modal-backdrop' },
        h(
          'div',
          { className: 'hct-modal' },
          h('div', { className: 'hct-modal-header' }, h('span', { className: 'hct-modal-title' }, '停止团队确认')),
          h(
            'div',
            { className: 'hct-modal-body' },
            h(
              'div',
              { style: { color: '#f87171', fontWeight: 600 } },
              `确认停止本施工团队「${activeTeam.name}」？`
            ),
            h(
              'div',
              { style: { fontSize: 12, lineHeight: 1.5, opacity: 0.85 } },
              '此操作仅停止该施工团队下属的任务派发与协作进程，绝不会停止宿主机其它团队或系统级主脑。正在运行的任务将保留现有工作区改动以便后续恢复。'
            ),
            h(
              'div',
              { className: 'hct-form-group', style: { marginTop: 8 } },
              h('label', { className: 'hct-label' }, '停止原因 (可选)'),
              h('input', {
                className: 'hct-input',
                placeholder: '例如: 本轮次施工完毕验收归档',
                value: formStopReason,
                onChange: e => setFormStopReason(e.target.value)
              })
            )
          ),
          h(
            'div',
            { className: 'hct-modal-footer' },
            h(
              'button',
              {
                className: 'hct-btn',
                onClick: () => {
                  setModalType(null)
                  setFormStopReason('')
                }
              },
              '取消'
            ),
            h(
              'button',
              {
                className: 'hct-btn hct-btn-danger',
                disabled: actionPending,
                onClick: handleConfirmStop
              },
              '确认停止本团队'
            )
          )
        )
      ),

    // 4.6 发送主管消息 / 纠偏指令模态框
    modalType === 'member_message' && modalTarget &&
      h(
        'div',
        { className: 'hct-modal-backdrop' },
        h(
          'div',
          { className: 'hct-modal' },
          h(
            'div',
            { className: 'hct-modal-header' },
            h(
              'span',
              { className: 'hct-modal-title' },
              modalTarget.status === 'running'
                ? `主管纠偏指令 (steer) - ${modalTarget.name}`
                : `向主管发消息 (message) - ${modalTarget.name}`
            )
          ),
          h(
            'form',
            { onSubmit: handleSendMessageSubmit },
            h(
              'div',
              { className: 'hct-modal-body' },
              h(
                'div',
                { style: { fontSize: 12, marginBottom: 8, color: 'var(--ui-text-secondary, #9ca3af)' } },
                modalTarget.status === 'running'
                  ? '主管当前处于 running 状态，必须以 steer 模式发送纠偏指令。'
                  : '主管当前处于空闲状态，将以 message 模式发送工作消息。'
              ),
              h(
                'div',
                { className: 'hct-form-group' },
                h('label', { className: 'hct-label' }, '消息/指令文本'),
                h('textarea', {
                  className: 'hct-textarea',
                  style: { minHeight: 90 },
                  placeholder: modalTarget.status === 'running' ? '输入纠偏指令内容...' : '输入向主管发送的消息内容...',
                  value: formMessageText,
                  onChange: e => setFormMessageText(e.target.value)
                })
              )
            ),
            h(
              'div',
              { className: 'hct-modal-footer' },
              h(
                'button',
                {
                  type: 'button',
                  className: 'hct-btn',
                  onClick: () => {
                    setModalType(null)
                    setModalTarget(null)
                    setFormMessageText('')
                  }
                },
                '取消'
              ),
              h(
                'button',
                {
                  type: 'submit',
                  className: 'hct-btn hct-btn-primary',
                  disabled: actionPending || !formMessageText.trim(),
                  onClick: handleSendMessageSubmit
                },
                actionPending ? '发送中...' : (modalTarget.status === 'running' ? '发送纠偏' : '发送消息')
              )
            )
          )
        )
      ),
      h(
        'datalist',
        { id: 'hct-models-datalist' },
        availableModels.map(m => h('option', { key: m, value: m }))
      ),
      h(
        'datalist',
        { id: 'hct-providers-datalist' },
        availableProviders.map(p => h('option', { key: p, value: p }))
      )
  )
}

// 侧边栏/浮窗概览组件
function ConstructionTeamPane({ ctx }) {
  const [teams, setTeams] = useState([])
  const [loading, setLoading] = useState(false)
  const epochRef = useRef(0)
  const readOwner = () => `${host?.state?.connectionId?.get?.() || ''}:${host?.state?.profile?.get?.() || 'default'}`
  const trackedProfileRef = useRef(readOwner())

  const fetchTeams = useCallback(async () => {
    const reqEpoch = epochRef.current
    setLoading(true)
    try {
      const data = await ctx.rest('/teams')
      if (epochRef.current !== reqEpoch) return
      if (data?.teams) {
        setTeams(data.teams)
      }
    } catch (err) {
      if (epochRef.current !== reqEpoch) return
      console.warn('[ConstructionTeamPane] error:', err)
    } finally {
      if (epochRef.current === reqEpoch) {
        setLoading(false)
      }
    }
  }, [ctx])

  useEffect(() => {
    fetchTeams()

    const onVisibleTick = () => {
      if (typeof document !== 'undefined' && document.hidden) return
      fetchTeams()
    }

    const unsubEvent = ctx?.onEvent
      ? ctx.onEvent(EVENT_NAME, onVisibleTick)
      : null

    const unsubInterval = ctx?.setInterval
      ? ctx.setInterval(onVisibleTick, POLL_INTERVAL_MS)
      : null

    const invalidate = () => {
      const owner = readOwner()
      if (owner === trackedProfileRef.current) return
      trackedProfileRef.current = owner
      epochRef.current += 1
      // 连接/Profile切换立即 clear 不是 load 后再 clear
      setTeams([])
      fetchTeams()
    }

    const disposers = [host?.state?.profile, host?.state?.connectionId]
      .map(atom => atom?.subscribe?.(invalidate))
      .filter(fn => typeof fn === 'function')

    return () => {
      if (typeof unsubEvent === 'function') unsubEvent()
      if (typeof unsubInterval === 'function') unsubInterval()
      disposers.forEach(dispose => {
        try { dispose() } catch {}
      })
    }
  }, [ctx, fetchTeams])

  return h(
    'div',
    {
      style: {
        padding: 12,
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        fontSize: 12
      }
    },
    h(
      'div',
      {
        style: {
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          borderBottom: '1px solid var(--ui-border, rgba(255,255,255,0.08))',
          paddingBottom: 6
        }
      },
      h('span', { style: { fontWeight: 600 } }, '施工团队概览'),
      h(
        'button',
        {
          className: 'hct-btn hct-btn-xs',
          onClick: () => {
            if (host && typeof host.navigate === 'function') {
              host.navigate(ROUTE_PATH)
            }
          }
        },
        '打开面板 ↗'
      )
    ),
    loading && h('div', { style: { opacity: 0.6 } }, '加载中...'),
    teams.length === 0
      ? h('div', { style: { opacity: 0.6, padding: '8px 0' } }, '暂无活跃团队')
      : teams.map(t =>
          h(
            'div',
            {
              key: t.id,
              style: {
                padding: '6px 8px',
                background: 'rgba(255,255,255,0.03)',
                borderRadius: 4,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                fontSize: 12
              }
            },
            h('span', { style: { fontWeight: 500 } }, t.name),
            h(StatusPill, { status: t.status })
          )
        )
  )
}

// 导出插件定义
export default {
  id: PLUGIN_ID,
  name: '施工团队',
  description: 'Hermes施工团队桌面插件：团队树、任务控制、主管会话联动与角色配置',

  register(ctx) {
    // Desktop loads plugins from Blob URLs, so a sibling CSS URL is not reliable.
    let styleElement = null
    if (typeof document !== 'undefined' && document.createElement && document.head) {
      styleElement = document.createElement('style')
      styleElement.dataset.constructionTeamStyle = '0.1.0'
      styleElement.textContent = EMBEDDED_STYLES
      document.head.appendChild(styleElement)
      ctx.onDispose?.(() => styleElement?.remove())
    }
    // 1. 注册工作区全页面路由 (ROUTES_AREA)
    const unregisterRoute = ctx.register({
      id: 'construction-team-route',
      area: ROUTES_AREA,
      title: '施工团队',
      data: { path: ROUTE_PATH },
      render: () => h(ConstructionTeamWorkspace, { ctx })
    })

    // 2. 注册左侧主导航图标 (SIDEBAR_NAV_AREA)
    const unregisterNav = ctx.register({
      id: 'construction-team-nav',
      area: SIDEBAR_NAV_AREA,
      data: {
        codicon: 'tools',
        label: '施工团队',
        path: ROUTE_PATH
      }
    })

    // 3. 注册侧边折叠面板 (PANES_AREA, pane hideOnly true)
    const unregisterPane = ctx.register({
      id: 'construction-team-pane',
      area: PANES_AREA,
      title: '施工团队',
      data: { placement: 'right', width: '280px', hideOnly: true },
      render: () => h(ConstructionTeamPane, { ctx })
    })

    // 返回整体注销函数
    return () => {
      styleElement?.remove()
      if (typeof unregisterRoute === 'function') unregisterRoute()
      if (typeof unregisterNav === 'function') unregisterNav()
      if (typeof unregisterPane === 'function') unregisterPane()
    }
  }
}

export { StatusPill, ConstructionTeamWorkspace, ConstructionTeamPane }
