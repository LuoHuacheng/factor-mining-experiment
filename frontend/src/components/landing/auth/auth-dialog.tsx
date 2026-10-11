"use client"

/**
 * 首页登录/注册弹窗 —— Tab 切换 + 模态面板
 */

import { useEffect, useState } from "react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog"
import { AuthLoginForm } from "./auth-login-form"
import { AuthRegisterForm } from "./auth-register-form"

export type AuthMode = "login" | "register"

interface AuthDialogProps {
  open: boolean
  initialMode: AuthMode
  onClose: () => void
}

/** 登录/注册弹窗 */
export function AuthDialog({
  open,
  initialMode,
  onClose,
}: AuthDialogProps): React.JSX.Element {
  const [mode, setMode] = useState<AuthMode>(initialMode)

  // 弹窗打开或外部 initialMode 变化时同步
  useEffect(() => {
    if (open) setMode(initialMode)
  }, [open, initialMode])

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-md max-h-[88vh] overflow-y-auto border-white/10 bg-[#121215]/95 backdrop-blur-xl">
        <div className="flex flex-col items-center mb-4">
          <span className="relative flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-red-500/90 to-red-800 shadow-[0_0_20px_rgba(239,68,68,0.35)] mb-3">
            <span className="text-base font-bold tracking-tight text-white">期</span>
            <span className="absolute -inset-px rounded-xl border border-red-400/40" />
          </span>
          <DialogTitle className="text-base font-semibold text-white">
            {mode === "login" ? "登录期货 AI 终端" : "注册账号"}
          </DialogTitle>
          <DialogDescription className="text-[11px] text-[var(--text-muted)] mt-1">
            AI 驱动的专业期货交易终端
          </DialogDescription>
        </div>

        {/* Tab 切换 */}
        <div className="grid grid-cols-2 gap-1 p-1 rounded-lg bg-black/40 border border-white/10 mb-4">
          <button
            type="button"
            onClick={() => setMode("login")}
            className={`h-8 rounded-md text-xs font-medium transition-colors ${
              mode === "login"
                ? "bg-red-500/25 text-red-100 border border-red-500/40"
                : "text-[var(--text-muted)] hover:text-white border border-transparent"
            }`}
          >
            登录
          </button>
          <button
            type="button"
            onClick={() => setMode("register")}
            className={`h-8 rounded-md text-xs font-medium transition-colors ${
              mode === "register"
                ? "bg-red-500/25 text-red-100 border border-red-500/40"
                : "text-[var(--text-muted)] hover:text-white border border-transparent"
            }`}
          >
            注册
          </button>
        </div>

        {mode === "login" ? (
          <AuthLoginForm
            onSuccess={onClose}
            onSwitchRegister={() => setMode("register")}
          />
        ) : (
          <AuthRegisterForm
            onSuccess={onClose}
            onSwitchLogin={() => setMode("login")}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}
