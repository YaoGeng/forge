import Link from "next/link";
import {
  ArrowRight,
  BadgeCheck,
  Blocks,
  Download,
  HeartPulse,
  ShieldCheck,
  Store,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Reveal } from "@/components/reveal";

/* docs/17-MS2执行计划.md L35 铁律原文（一字不差，不得转写）：
   页脚声明原文一字不差："运行条件与成功率以信任字段为准；平台审核与认证不构成对运行结果的担保" */
const WARRANTY_TEXT =
  "运行条件与成功率以信任字段为准；平台审核与认证不构成对运行结果的担保";

/** 通过率环（示意，静态 SVG；数值取自原型信任字段示例） */
function RateRing() {
  const R = 52;
  const C = 2 * Math.PI * R;
  const RATE = 0.9;
  return (
    <svg
      viewBox="0 0 128 128"
      className="size-32 shrink-0"
      role="img"
      aria-label="示意：实测通过率 90%，近 20 次真实运行"
    >
      <circle className="ring-track" cx="64" cy="64" r={R} fill="none" strokeWidth="10" />
      <circle
        className="ring-bar"
        cx="64"
        cy="64"
        r={R}
        fill="none"
        strokeWidth="10"
        strokeDasharray={C}
        strokeDashoffset={C * (1 - RATE)}
      />
      <text
        x="64"
        y="60"
        textAnchor="middle"
        className="fill-foreground text-[26px] font-semibold"
      >
        90%
      </text>
      <text x="64" y="82" textAnchor="middle" className="fill-ink-soft text-[11px]">
        近 20 次真实运行
      </text>
    </svg>
  );
}

const FEATURES = [
  {
    icon: Blocks,
    title: "积木 · 认证积木组装",
    lead: "应用由认证积木组装，可靠性逐块透明。",
    points: [
      "逐块展示纯真实运行实测通过率（带样本量）",
      "串联流程不展示合成通过率——合成值是推算而非实测",
      "发布前整链真实运行验证 1 次，结果如实标注（N=1，非统计值）",
    ],
  },
  {
    icon: ShieldCheck,
    title: "认证 · 认证流水线放行",
    lead: "演示录制参数化，认证流水线放行，才配上架。",
    points: [
      "C1 登录流程认证：本机认证器 · N≥20 真实运行",
      "签名认证报告 + 平台抽查复核",
      "高变更站点应用显著标注 best-effort（不可折叠）",
    ],
  },
  {
    icon: HeartPulse,
    title: "健康分 · 用户运行上报",
    lead: "买家自愿上报运行结果，让可靠性越来越真实。",
    points: [
      "上报运行结果（不含任何页面内容），参与「用户运行成功率」与健康分统计",
      "user-side 类失败不计入积木健康分，归因口径公开",
      "健康分影响橱窗曝光，修复响应时效仅作曝光微调因子",
    ],
  },
] as const;

const TRUST_RULES = [
  {
    term: "实测通过率",
    desc: "任何通过率不带样本量不得渲染数字；不足最小样本显示「数据不足」。逐次测量，带测量时间。",
  },
  {
    term: "认证等级",
    desc: "组成积木逐块标注认证等级（如 C1 登录流程认证），认证积木拼装的应用才允许上架。",
  },
  {
    term: "best-effort 标注",
    desc: "高变更频率站点应用首屏显著标注，不可折叠——买之前就看到边界，而不是出事后。",
  },
  {
    term: "没有五星评分",
    desc: "五星评分延后引入——实测通过率就是最好的评分。",
  },
] as const;

export default function Home() {
  return (
    <div className="relative flex min-h-screen flex-col overflow-x-clip">
      {/* 背景光晕层（纯 CSS 动画，原型 .orbs 同款） */}
      <div className="orbs" aria-hidden="true">
        <div className="orb orb-1" />
        <div className="orb orb-2" />
        <div className="orb orb-3" />
        <div className="orb orb-4" />
      </div>

      {/* ============ 顶栏 ============ */}
      <header className="site-header sticky top-0 z-40">
        <div className="mx-auto flex h-16 w-full max-w-6xl items-center justify-between gap-4 px-5">
          <a href="#" className="flex items-center gap-2.5" aria-label="Forge 首页">
            <span className="logo-tile grid size-9 place-items-center rounded-xl text-lg font-bold">
              F
            </span>
            <span className="flex flex-col leading-tight">
              <span className="text-base font-semibold tracking-wide">Forge</span>
              <span className="text-[11px] text-ink-soft">AI 自动化应用平台</span>
            </span>
          </a>
          <nav aria-label="页面导航" className="hidden items-center gap-6 text-sm text-ink-soft md:flex">
            <a className="transition-colors hover:text-primary" href="#features">三大支柱</a>
            <a className="transition-colors hover:text-primary" href="#trust">信任字段</a>
            <a className="transition-colors hover:text-primary" href="#download">下载</a>
          </nav>
          <Button asChild className="bg-brand h-9 px-4 text-white hover:bg-brand-deep">
            <Link href="/store">
              浏览商店
              <ArrowRight data-icon="inline-end" />
            </Link>
          </Button>
        </div>
      </header>

      <main className="flex-1">
        {/* ============ Hero ============ */}
        <section className="mx-auto w-full max-w-6xl px-5 pb-20 pt-16 md:pt-24">
          <div className="grid items-center gap-10 lg:grid-cols-[1.1fr_0.9fr]">
            <Reveal>
              <Badge
                className="h-auto border-warn-line bg-warn-bg px-3 py-1.5 text-[13px] text-warn"
                variant="outline"
              >
                <span className="ring-dot-pulse mr-1 inline-block size-1.5 rounded-full bg-warn" />
                可靠性是测出来的，不是生成出来的
              </Badge>
              <h1 className="headline-gradient mt-5 text-4xl leading-[1.25] font-semibold tracking-[0.01em] md:text-5xl">
                买之前，
                <br />
                就知道它
                <span className="headline-underline">能不能跑</span>。
              </h1>
              <p className="mt-5 max-w-[52ch] text-[15px] leading-relaxed text-ink-soft">
                每个应用详情页都印着<strong className="font-semibold text-foreground">实测通过率</strong>
                ——来自真实运行的逐次测量，带样本量与测量时间。认证积木组装，演示录制参数化，认证流水线放行，才配上架。
              </p>
              <div className="mt-8 flex flex-wrap items-center gap-4">
                <Button
                  asChild
                  size="lg"
                  className="bg-brand h-12 px-7 text-base text-white hover:bg-brand-deep"
                >
                  <Link href="/store">
                    <Store data-icon="inline-start" />
                    浏览商店
                    <ArrowRight data-icon="inline-end" />
                  </Link>
                </Button>
                <Button
                  asChild
                  size="lg"
                  variant="outline"
                  className="h-12 border-primary/30 bg-white/60 px-7 text-base text-primary hover:bg-white/85"
                >
                  <Link href="/download/">
                    <Download data-icon="inline-start" />
                    下载客户端
                  </Link>
                </Button>
              </div>
              <p className="mt-4 text-[13px] text-ink-soft">
                买断制 · 含 12 个月维护期 · Token 完全自付
              </p>
            </Reveal>

            <Reveal delay={160}>
              <div className="glass-card glass-strong feature-card p-7">
                <div className="flex items-center gap-2">
                  <Badge variant="outline" className="border-brand-soft bg-brand-bg text-brand-ink">
                    示意
                  </Badge>
                  <span className="text-[13px] text-ink-soft">应用详情页的信任字段长这样</span>
                </div>
                <div className="mt-6 flex items-center gap-6">
                  <RateRing />
                  <div className="flex flex-col gap-2.5">
                    <span className="text-sm font-medium">小红书选品日报</span>
                    <div className="flex flex-wrap gap-1.5">
                      <Badge className="bg-secondary text-secondary-foreground">C1 登录流程认证</Badge>
                      <Badge variant="outline" className="border-warn-line bg-warn-bg text-warn">
                        <span className="ring-dot-pulse mr-1 inline-block size-1.5 rounded-full bg-warn" />
                        best-effort · 高变更站点
                      </Badge>
                    </div>
                    <span className="text-[12px] text-ink-soft">
                      实测通过率（近 20 次真实运行实测，2026-10）
                    </span>
                  </div>
                </div>
                <p className="mt-6 border-t border-border pt-4 text-[12.5px] leading-relaxed text-ink-soft">
                  五星评分延后引入——<span className="text-brand-ink font-medium">实测通过率</span>就是最好的评分。
                </p>
              </div>
            </Reveal>
          </div>
        </section>

        {/* ============ 三大支柱 ============ */}
        <section id="features" className="mx-auto w-full max-w-6xl scroll-mt-20 px-5 py-16">
          <Reveal>
            <h2 className="text-2xl font-semibold md:text-3xl">可靠性不是口号，是三道工序</h2>
            <p className="mt-3 max-w-[60ch] text-[15px] text-ink-soft">
              积木逐块实测、认证流水线放行、买家运行上报持续校准——三个环节全部可查证。
            </p>
          </Reveal>
          <div className="mt-10 grid gap-6 md:grid-cols-3">
            {FEATURES.map((f, i) => (
              <Reveal key={f.title} delay={i * 120}>
                <div className="glass-card feature-card h-full p-6">
                  <span className="logo-tile grid size-11 place-items-center rounded-xl">
                    <f.icon className="size-5" strokeWidth={1.8} aria-hidden="true" />
                  </span>
                  <h3 className="mt-4 text-lg font-semibold">{f.title}</h3>
                  <p className="mt-1.5 text-sm text-ink-soft">{f.lead}</p>
                  <ul className="mt-4 flex flex-col gap-2.5">
                    {f.points.map((p) => (
                      <li key={p} className="flex gap-2 text-[13.5px] leading-relaxed">
                        <BadgeCheck
                          className="mt-0.5 size-4 shrink-0 text-moss"
                          strokeWidth={2}
                          aria-hidden="true"
                        />
                        <span className="text-ink-soft">{p}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </Reveal>
            ))}
          </div>
        </section>

        {/* ============ 信任字段说明 ============ */}
        <section id="trust" className="mx-auto w-full max-w-6xl scroll-mt-20 px-5 py-16">
          <Reveal>
            <div className="glass-card p-8 md:p-10">
              <div className="flex flex-wrap items-baseline gap-x-3">
                <h2 className="text-2xl font-semibold md:text-3xl">信任字段说明</h2>
                <span className="text-[13px] text-ink-soft">买之前，先看这里</span>
              </div>
              <dl className="mt-8 grid gap-x-10 gap-y-7 md:grid-cols-2">
                {TRUST_RULES.map((r, i) => (
                  <Reveal key={r.term} delay={i * 100} as="div">
                    <dt className="flex items-center gap-2 text-[15px] font-semibold">
                      <span className="inline-block h-4 w-1 rounded-full bg-moss" aria-hidden="true" />
                      {r.term}
                    </dt>
                    <dd className="mt-2 pl-3 text-[13.5px] leading-relaxed text-ink-soft">
                      {r.desc}
                    </dd>
                  </Reveal>
                ))}
              </dl>
            </div>
          </Reveal>
        </section>

        {/* ============ CTA ============ */}
        <section id="download" className="mx-auto w-full max-w-6xl scroll-mt-20 px-5 py-16">
          <Reveal>
            <div className="glass-card glass-strong relative overflow-hidden p-10 text-center md:p-14">
              <div
                className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top,rgba(107,142,90,0.16),transparent_60%)]"
                aria-hidden="true"
              />
              <h2 className="relative text-2xl font-semibold md:text-3xl">
                去看带着实测数据的应用
              </h2>
              <p className="relative mx-auto mt-3 max-w-[52ch] text-[15px] text-ink-soft">
                商店里每个应用都印着实测通过率、认证等级与 best-effort 标注；桌面客户端开箱即用，任务空闲时自动更新。
              </p>
              <div className="relative mt-8 flex flex-wrap items-center justify-center gap-4">
                <Button
                  asChild
                  size="lg"
                  className="bg-brand h-12 px-8 text-base text-white hover:bg-brand-deep"
                >
                  <Link href="/store">
                    <Store data-icon="inline-start" />
                    浏览商店
                    <ArrowRight data-icon="inline-end" />
                  </Link>
                </Button>
                <Button
                  asChild
                  size="lg"
                  variant="outline"
                  className="h-12 border-primary/30 bg-white/60 px-8 text-base text-primary hover:bg-white/85"
                >
                  <Link href="/download/">
                    <Download data-icon="inline-start" />
                    下载客户端
                  </Link>
                </Button>
              </div>
              <p className="relative mt-4 text-[13px] text-ink-soft">
                买断制 · Token 完全自付 · 运行结果参与健康分统计完全自愿
              </p>
            </div>
          </Reveal>
        </section>
      </main>

      {/* ============ Footer ============ */}
      <footer className="border-t border-border bg-white/40">
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 px-5 py-10">
          <div className="flex flex-wrap items-center gap-2.5">
            <span className="logo-tile grid size-8 place-items-center rounded-lg text-base font-bold">
              F
            </span>
            <span className="text-sm font-semibold">Forge · AI 自动化应用平台</span>
          </div>
          {/* 担保声明：docs/17-MS2执行计划.md 铁律原文，逐字引用不得转写 */}
          <p className="max-w-[80ch] text-[13px] leading-relaxed text-ink-soft">
            {WARRANTY_TEXT}
          </p>
          <nav aria-label="页脚导航" className="flex flex-wrap items-center gap-5 text-[13px]">
            <Link className="text-primary underline-offset-4 hover:underline" href="/store">
              应用商店
            </Link>
            <Link className="text-primary underline-offset-4 hover:underline" href="/download/">
              客户端下载
            </Link>
            <span className="text-ink-soft">© 2026 Forge</span>
          </nav>
        </div>
      </footer>
    </div>
  );
}
