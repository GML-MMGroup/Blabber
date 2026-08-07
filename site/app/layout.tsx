import type { Metadata } from "next";
import { headers } from "next/headers";
import "./globals.css";

export async function generateMetadata(): Promise<Metadata> {
  const incoming = await headers();
  const host = incoming.get("x-forwarded-host") ?? incoming.get("host") ?? "localhost:3000";
  const protocol = incoming.get("x-forwarded-proto") ?? (host.includes("localhost") ? "http" : "https");
  const origin = `${protocol}://${host}`;
  const title = "Blabber Studio — 动画播客制作工作台";
  const description = "从可编辑脚本到角色、场景、音色与视频合成，在一个工作台完成动画播客制作。";

  return {
    metadataBase: new URL(origin),
    title,
    description,
    icons: { icon: "/favicon.svg" },
    openGraph: {
      title,
      description,
      images: [{ url: `${origin}/og-studio.png`, width: 1733, height: 909, alt: "Blabber Studio 动画播客制作工作台" }],
      type: "website",
    },
    twitter: { card: "summary_large_image", title, description, images: [`${origin}/og-studio.png`] },
  };
}

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
