"use client";

import { BorderBeam } from "border-beam";
import type { CSSProperties, ReactElement } from "react";

type GenerationBeamProps = {
  active: boolean;
  borderRadius: number;
  children: ReactElement;
  className: string;
  size: "sm" | "pulse-inner";
};

export default function GenerationBeam({ active, borderRadius, children, className, size }: GenerationBeamProps) {
  if (!active) return children;

  return <BorderBeam
    active
    borderRadius={borderRadius}
    brightness={size === "pulse-inner" ? 0.98 : 1.16}
    className={className}
    colorVariant="ocean"
    duration={size === "pulse-inner" ? 2.4 : 1.85}
    hueRange={size === "pulse-inner" ? 5 : 30}
    saturation={size === "pulse-inner" ? 0.72 : 1.18}
    size={size}
    strength={size === "pulse-inner" ? 0.46 : 0.88}
    style={size === "pulse-inner" ? ({ "--beam-hue-base": "18deg" } as CSSProperties) : undefined}
    theme="light"
  >{children}</BorderBeam>;
}
