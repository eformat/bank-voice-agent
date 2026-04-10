import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Fed Aura Capital - AI Banking Assistant",
  description: "AI Voice & Chat Agent - Fed Aura Capital",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head>
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Red+Hat+Display:wght@400;500;600;700;900&family=Red+Hat+Text:wght@400;500;600;700&display=swap"
        />
      </head>
      <body className="antialiased">
        {children}
      </body>
    </html>
  );
}
