import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MySathi Admin Console",
  description: "Private chatbot usage and conversation dashboard.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
