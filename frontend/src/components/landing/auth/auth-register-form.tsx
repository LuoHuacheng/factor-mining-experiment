"use client"

/**
 * 首页注册弹窗表单 —— 复用注册 API 与注册策略提示
 */

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { useAuthStore } from "@/stores/auth"
import { getMeApi, registerApi } from "@/lib/api"
import { getRegistrationStatusApi } from "@/lib/admin-api"
import type { RegistrationStatus } from "@/lib/admin-api"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"

interface RegisterFormState {
  username: string
  phone: string
  password: string
  confirmPassword: string
  agreement: boolean
}

const EMPTY_FORM: RegisterFormState = {
  username: "",
  phone: "",
  password: "",
  confirmPassword: "",
  agreement: false,
}

interface AuthRegisterFormProps {
  onSuccess: () => void
  onSwitchLogin: () => void
}

/** 注册表单（弹窗内） */
export function AuthRegisterForm({
  onSuccess,
  onSwitchLogin,
}: AuthRegisterFormProps): React.JSX.Element {
  const router = useRouter()
  const login = useAuthStore((s) => s.login)
  const [form, setForm] = useState<RegisterFormState>(EMPTY_FORM)
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)
  const [regStatus, setRegStatus] = useState<RegistrationStatus | null>(null)
  const [statusLoading, setStatusLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    async function load(): Promise<void> {
      try {
        const s = await getRegistrationStatusApi()
        if (!cancelled) setRegStatus(s)
      } catch {
        if (!cancelled) setRegStatus(null)
      } finally {
        if (!cancelled) setStatusLoading(false)
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [])

  function updateField(field: keyof RegisterFormState, value: string | boolean): void {
    setForm((prev) => ({ ...prev, [field]: value }))
  }

  async function handleSubmit(e: React.FormEvent): Promise<void> {
    e.preventDefault()
    setError("")
    if (regStatus && !regStatus.can_register) {
      setError(regStatus.reason || "当前不可注册")
      return
    }
    if (form.password !== form.confirmPassword) {
      setError("两次密码输入不一致")
      return
    }
    if (!form.agreement) {
      setError("请阅读并同意用户协议")
      return
    }
    if (form.username.length < 3) {
      setError("用户名至少 3 个字符")
      return
    }
    if (form.password.length < 6) {
      setError("密码至少 6 个字符")
      return
    }

    setLoading(true)
    try {
      const authRes = await registerApi({
        username: form.username,
        password: form.password,
        phone: form.phone || null,
      })
      localStorage.setItem("access_token", authRes.access_token)
      localStorage.setItem("refresh_token", authRes.refresh_token)
      useAuthStore.setState({ accessToken: authRes.access_token })
      const user = await getMeApi()
      login(user, authRes.access_token, authRes.refresh_token)
      onSuccess()
      router.push("/dashboard")
    } catch (err) {
      setError(err instanceof Error ? err.message : "注册失败，请重试")
    } finally {
      setLoading(false)
    }
  }

  const blocked = Boolean(regStatus && !regStatus.can_register)

  return (
    <form onSubmit={handleSubmit} className="space-y-3.5">
      {statusLoading && (
        <p className="text-xs text-center text-[var(--text-muted)]">
          正在检查注册状态…
        </p>
      )}

      {!statusLoading && regStatus && (
        <div
          className={`px-3.5 py-2 rounded-md text-xs text-center ${
            blocked
              ? "bg-red-500/15 text-red-300"
              : "bg-red-500/10 text-[var(--text-secondary)]"
          }`}
        >
          {blocked ? (
            <span>{regStatus.reason || "当前不可注册"}</span>
          ) : (
            <span>
              开放注册
              {regStatus.daily_register_limit > 0 && (
                <>
                  ，今日剩余{" "}
                  <strong className="text-[var(--text-primary)]">
                    {regStatus.remaining ?? 0}
                  </strong>{" "}
                  / {regStatus.daily_register_limit}
                </>
              )}
            </span>
          )}
        </div>
      )}

      {error && (
        <div className="px-3.5 py-2 rounded-md bg-red-500/15 text-red-300 text-xs text-center">
          {error}
        </div>
      )}

      <div className="space-y-1.5">
        <Label htmlFor="reg-username">用户名</Label>
        <Input
          id="reg-username"
          placeholder="字母/数字/下划线，至少 3 位"
          value={form.username}
          onChange={(e) => updateField("username", e.target.value)}
          required
          disabled={blocked}
        />
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="reg-phone">手机号（可选）</Label>
        <Input
          id="reg-phone"
          placeholder="请输入手机号"
          value={form.phone}
          onChange={(e) => updateField("phone", e.target.value)}
          disabled={blocked}
        />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1.5">
          <Label htmlFor="reg-password">密码</Label>
          <Input
            id="reg-password"
            type="password"
            placeholder="至少 6 位"
            value={form.password}
            onChange={(e) => updateField("password", e.target.value)}
            required
            disabled={blocked}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="reg-confirm">确认密码</Label>
          <Input
            id="reg-confirm"
            type="password"
            placeholder="再次输入"
            value={form.confirmPassword}
            onChange={(e) => updateField("confirmPassword", e.target.value)}
            required
            disabled={blocked}
          />
        </div>
      </div>

      <label className="flex items-start gap-2 text-xs text-[var(--text-muted)]">
        <input
          type="checkbox"
          checked={form.agreement}
          onChange={(e) => updateField("agreement", e.target.checked)}
          disabled={blocked}
          className="w-3.5 h-3.5 mt-0.5 rounded border-white/15 bg-transparent accent-red-500"
        />
        <span>
          我已阅读并同意
          <span className="text-red-300">《用户协议》</span>和
          <span className="text-red-300">《隐私政策》</span>
        </span>
      </label>

      <button
        type="submit"
        disabled={loading || blocked || statusLoading}
        className="w-full h-10 rounded-md bg-gradient-to-r from-red-600 to-red-500 text-white text-sm font-medium shadow-[0_0_20px_rgba(239,68,68,0.3)] hover:from-red-500 hover:to-red-400 disabled:opacity-60 transition-colors duration-200"
      >
        {loading ? "注册中..." : blocked ? "暂不可注册" : "注册"}
      </button>

      <p className="text-center text-xs text-[var(--text-muted)]">
        已有账号？
        <button
          type="button"
          onClick={onSwitchLogin}
          className="ml-1 text-red-300 hover:text-red-200 hover:underline"
        >
          立即登录
        </button>
      </p>
    </form>
  )
}
