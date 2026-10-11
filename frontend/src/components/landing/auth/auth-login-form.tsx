"use client"

/**
 * 首页登录弹窗表单 —— 复用登录 API 与「记住密码」逻辑
 */

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { useAuthStore } from "@/stores/auth"
import { getMeApi, loginApi } from "@/lib/api"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"

const REMEMBER_KEY = "qihuo_login_remember"
const SAVED_USER_KEY = "qihuo_login_username"
const SAVED_PASS_KEY = "qihuo_login_password"

interface RememberedInfo {
  username: string
  password: string
  remember: boolean
}

/** 读取本地保存的登录信息 */
function loadRemembered(): RememberedInfo {
  if (typeof window === "undefined") {
    return { username: "", password: "", remember: false }
  }
  try {
    const remember = localStorage.getItem(REMEMBER_KEY) === "1"
    if (!remember) return { username: "", password: "", remember: false }
    return {
      username: localStorage.getItem(SAVED_USER_KEY) ?? "",
      password: localStorage.getItem(SAVED_PASS_KEY) ?? "",
      remember: true,
    }
  } catch {
    return { username: "", password: "", remember: false }
  }
}

/** 写入或清除记住的密码 */
function persistRemember(
  remember: boolean,
  username: string,
  password: string,
): void {
  try {
    if (remember) {
      localStorage.setItem(REMEMBER_KEY, "1")
      localStorage.setItem(SAVED_USER_KEY, username)
      localStorage.setItem(SAVED_PASS_KEY, password)
    } else {
      localStorage.removeItem(REMEMBER_KEY)
      localStorage.removeItem(SAVED_USER_KEY)
      localStorage.removeItem(SAVED_PASS_KEY)
    }
  } catch {
    // 隐私模式等写失败忽略
  }
}

interface AuthLoginFormProps {
  onSuccess: () => void
  onSwitchRegister: () => void
}

/** 登录表单（弹窗内） */
export function AuthLoginForm({
  onSuccess,
  onSwitchRegister,
}: AuthLoginFormProps): React.JSX.Element {
  const router = useRouter()
  const login = useAuthStore((s) => s.login)
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [tradingMode, setTradingMode] = useState<"live" | "virtual">("live")
  const [remember, setRemember] = useState(false)
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)
  const [hydrated, setHydrated] = useState(false)

  useEffect(() => {
    const saved = loadRemembered()
    setUsername(saved.username)
    setPassword(saved.password)
    setRemember(saved.remember)
    setHydrated(true)
  }, [])

  async function handleSubmit(e: React.FormEvent): Promise<void> {
    e.preventDefault()
    setError("")
    setLoading(true)
    try {
      const authRes = await loginApi({
        account: username,
        password,
        trading_mode: tradingMode,
      })
      localStorage.setItem("access_token", authRes.access_token)
      localStorage.setItem("refresh_token", authRes.refresh_token)
      useAuthStore.setState({ accessToken: authRes.access_token })
      persistRemember(remember, username, password)
      const user = await getMeApi()
      login(
        { ...user, trading_mode: user.trading_mode ?? tradingMode },
        authRes.access_token,
        authRes.refresh_token,
      )
      onSuccess()
      router.push("/dashboard")
    } catch (err) {
      setError(err instanceof Error ? err.message : "账号或密码错误")
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {error && (
        <div className="px-3.5 py-2 rounded-md bg-red-500/15 text-red-300 text-xs text-center">
          {error}
        </div>
      )}

      <div className="space-y-1.5">
        <Label htmlFor="auth-username">用户名</Label>
        <Input
          id="auth-username"
          placeholder="请输入用户名"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
          required
        />
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="auth-password">密码</Label>
        <Input
          id="auth-password"
          type="password"
          placeholder="请输入密码"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete={remember ? "current-password" : "off"}
          required
        />
      </div>

      <div className="space-y-1.5">
        <Label>数据盘（登录后不可切换）</Label>
        <div className="grid grid-cols-2 gap-2">
          <button
            type="button"
            onClick={() => setTradingMode("live")}
            className={`h-9 rounded-md border text-xs transition-colors ${
              tradingMode === "live"
                ? "border-red-500/60 bg-red-500/15 text-red-200"
                : "border-white/10 text-[var(--text-secondary)] hover:border-white/25"
            }`}
          >
            实盘数据
          </button>
          <button
            type="button"
            onClick={() => setTradingMode("virtual")}
            className={`h-9 rounded-md border text-xs transition-colors ${
              tradingMode === "virtual"
                ? "border-amber-500/60 bg-amber-500/15 text-amber-200"
                : "border-white/10 text-[var(--text-secondary)] hover:border-white/25"
            }`}
          >
            虚拟盘
          </button>
        </div>
        <p className="text-[11px] text-[var(--text-muted)] leading-relaxed">
          {tradingMode === "live"
            ? "实盘：新浪/SimNow 行情 + 当前模拟账户体系"
            : "虚拟盘：openctp 7×24 行情 + 独立资金/持仓/任务"}
        </p>
      </div>

      <div className="flex items-center justify-between">
        <label className="flex items-center gap-2 text-xs text-[var(--text-secondary)] cursor-pointer select-none">
          <input
            type="checkbox"
            checked={remember}
            onChange={(e) => {
              const next = e.target.checked
              setRemember(next)
              if (!next) persistRemember(false, "", "")
            }}
            className="w-3.5 h-3.5 rounded border-white/15 bg-transparent accent-red-500"
          />
          记住密码
        </label>
        <span className="text-[11px] text-[var(--text-muted)]">有效期 7 天</span>
      </div>

      <button
        type="submit"
        disabled={loading || !hydrated}
        className="w-full h-10 rounded-md bg-gradient-to-r from-red-600 to-red-500 text-white text-sm font-medium shadow-[0_0_20px_rgba(239,68,68,0.3)] hover:from-red-500 hover:to-red-400 disabled:opacity-60 transition-colors duration-200"
      >
        {loading ? "登录中..." : "登录"}
      </button>

      <p className="text-center text-xs text-[var(--text-muted)]">
        还没有账号？
        <button
          type="button"
          onClick={onSwitchRegister}
          className="ml-1 text-red-300 hover:text-red-200 hover:underline"
        >
          立即注册
        </button>
      </p>
    </form>
  )
}
