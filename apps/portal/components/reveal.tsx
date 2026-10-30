"use client";

import * as React from "react";
import { cn } from "cn";

/**
 * 滚动渐入容器：IntersectionObserver 驱动，进入视口即加 .is-visible。
 * 纯 CSS 过渡（见 globals.css .reveal），不引动效库；
 * prefers-reduced-motion 下由 CSS 直接呈现终态。
 */
export function Reveal({
  children,
  className,
  delay = 0,
  as: Tag = "div",
}: {
  children: React.ReactNode;
  className?: string;
  /** 交错延迟（毫秒），写到 --reveal-delay */
  delay?: number;
  as?: "div" | "section" | "li" | "span";
}) {
  const ref = React.useRef<HTMLElement | null>(null);

  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (typeof IntersectionObserver === "undefined") {
      el.classList.add("is-visible");
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            observer.unobserve(entry.target);
          }
        }
      },
      { threshold: 0.15, rootMargin: "0px 0px -8% 0px" },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <Tag
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      ref={ref as React.Ref<any>}
      className={cn("reveal", className)}
      style={delay ? ({ "--reveal-delay": `${delay}ms` } as React.CSSProperties) : undefined}
    >
      {children}
    </Tag>
  );
}
