import { data } from "@/lib/data";

export const runtime = "nodejs";

export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const generation = await data.getRouteGeneration(id);
  if (!generation) return Response.json({ error: "Not found" }, { status: 404 });
  return Response.json({ generation });
}
