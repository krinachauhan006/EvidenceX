import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "EvidenceX · Multimodal evidence investigation",
    template: "%s",
  },
  description:
    "EvidenceX connects documents, images, audio, video, email and spreadsheets into one " +
    "source-anchored investigation workspace with human review.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
