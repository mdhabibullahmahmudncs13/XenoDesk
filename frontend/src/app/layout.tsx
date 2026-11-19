import "../styles/globals.css";
import { AppShell } from "../components/AppShell";

export const metadata = {
  title: "XenoDesk",
  description: "Customer understanding and creator commerce workspace",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
