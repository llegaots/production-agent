import { Sidebar } from "@/components/layout/sidebar";
import { Topbar } from "@/components/layout/topbar";
import { MobileNav } from "@/components/layout/mobile-nav";
import { PageTransition } from "@/components/layout/page-transition";
import { Providers } from "@/components/providers";
import { data } from "@/lib/data";

export const dynamic = "force-dynamic";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const liveCount = (await data.getLiveSessions()).length;

  return (
    <Providers>
      <div className="flex min-h-screen">
        <Sidebar liveCount={liveCount} />
        <div className="flex min-w-0 flex-1 flex-col">
          <MobileNav />
          <Topbar liveCount={liveCount} />
          <main className="flex-1 px-5 py-6 lg:px-8 lg:py-7">
            <PageTransition>{children}</PageTransition>
          </main>
        </div>
      </div>
    </Providers>
  );
}
