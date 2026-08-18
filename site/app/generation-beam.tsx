"use client";

import { BorderBeam } from "border-beam";
import type { ReactElement } from "react";

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
    brightness={size === "pulse-inner" ? 1.08 : 1.16}
    className={className}
    colorVariant="ocean"
    duration={size === "pulse-inner" ? 2.4 : 1.85}
    size={size}
    strength={size === "pulse-inner" ? 0.72 : 0.88}
    theme="light"
  >{children}</BorderBeam>;
}
