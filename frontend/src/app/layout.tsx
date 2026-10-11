import type { Metadata } from "next"
import "./globals.css"
import { FontSizeProvider } from "@/components/common/font-size-provider"

export const metadata: Metadata = {
  title: "期货交易系统",
  description: "AI驱动的期货交易系统",
}

/** 首屏前恢复字号，避免闪一下再变大 */
const FONT_SIZE_BOOT_SCRIPT = `(function(){try{var k='qihuo_font_size';var s=localStorage.getItem(k)||'standard';var ok={standard:1,large:1,xlarge:1,xxlarge:1};if(!ok[s])s='standard';document.documentElement.setAttribute('data-font-size',s);}catch(e){document.documentElement.setAttribute('data-font-size','standard');}})();`

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="zh-CN" className="dark" data-font-size="standard">
      <head>
        <script dangerouslySetInnerHTML={{ __html: FONT_SIZE_BOOT_SCRIPT }} />
      </head>
      <body className="antialiased font-sans">
        <FontSizeProvider />
        {children}
      </body>
    </html>
  )
}
