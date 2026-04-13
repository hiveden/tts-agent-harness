import type { Metadata } from "next";
import { ThemeProvider } from "next-themes";
import { ThemedToaster } from "@/components/ThemedToaster";
import "./globals.css";

export const metadata: Metadata = {
  title: "TTS Harness",
  description: "TTS Agent Harness — local production UI",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh" className="h-full antialiased" suppressHydrationWarning>
      <body className="h-full bg-white dark:bg-neutral-900 text-neutral-900 dark:text-neutral-100">
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
          {children}
          <ThemedToaster />
        </ThemeProvider>
      </body>
    </html>
  );
}
