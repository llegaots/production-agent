import { ChatShell } from "@/components/chat/chat-shell";

type Props = {
  params: Promise<{ sessionId: string }>;
};

export default async function ChatSessionPage({ params }: Props) {
  const { sessionId } = await params;
  return <ChatShell sessionId={sessionId} />;
}
