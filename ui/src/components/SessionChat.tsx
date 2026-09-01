import { FormEvent, Fragment, ReactNode, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { ChatTurnDTO } from "../api/types";
import { useRunStore } from "../liveworkflow/runStore";

interface DisplayMessage extends ChatTurnDTO {
  id: string;
}

function ChatbotIcon() {
  return (
    <svg viewBox="0 0 24 24" width="19" height="19" fill="none" aria-hidden="true">
      <path d="M8 4.5h8a4 4 0 0 1 4 4v4.75a4 4 0 0 1-4 4h-4.7L7 20v-2.75A4 4 0 0 1 4 13.4V8.5a4 4 0 0 1 4-4Z" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
      <path d="M9 10.5h.01M15 10.5h.01M9.5 14h5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <path d="M12 4.5V2.75" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}

function InlineMarkdown({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).filter(Boolean);
  return (
    <>
      {parts.map((part, index) => {
        if (part.startsWith("**") && part.endsWith("**")) {
          return <strong key={index}>{part.slice(2, -2)}</strong>;
        }
        if (part.startsWith("`") && part.endsWith("`")) {
          return <code key={index}>{part.slice(1, -1)}</code>;
        }
        return <Fragment key={index}>{part}</Fragment>;
      })}
    </>
  );
}

function FormattedAnswer({ content }: { content: string }) {
  const lines = content.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index].trim();
    if (!line) {
      index += 1;
      continue;
    }
    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      blocks.push(
        <h4 key={`heading-${index}`}>
          <InlineMarkdown text={heading[2]} />
        </h4>,
      );
      index += 1;
      continue;
    }
    const unordered = line.match(/^[-*]\s+(.+)$/);
    if (unordered) {
      const items: string[] = [];
      while (index < lines.length) {
        const match = lines[index].trim().match(/^[-*]\s+(.+)$/);
        if (!match) break;
        items.push(match[1]);
        index += 1;
      }
      blocks.push(
        <ul key={`list-${index}`}>
          {items.map((item, itemIndex) => <li key={itemIndex}><InlineMarkdown text={item} /></li>)}
        </ul>,
      );
      continue;
    }
    const ordered = line.match(/^\d+[.)]\s+(.+)$/);
    if (ordered) {
      const items: string[] = [];
      while (index < lines.length) {
        const match = lines[index].trim().match(/^\d+[.)]\s+(.+)$/);
        if (!match) break;
        items.push(match[1]);
        index += 1;
      }
      blocks.push(
        <ol key={`ordered-${index}`}>
          {items.map((item, itemIndex) => <li key={itemIndex}><InlineMarkdown text={item} /></li>)}
        </ol>,
      );
      continue;
    }
    if (line.startsWith("> ")) {
      blocks.push(<blockquote key={`quote-${index}`}><InlineMarkdown text={line.slice(2)} /></blockquote>);
      index += 1;
      continue;
    }
    const paragraph: string[] = [line];
    index += 1;
    while (
      index < lines.length
      && lines[index].trim()
      && !/^(#{1,3})\s+|^[-*]\s+|^\d+[.)]\s+|^>\s+/.test(lines[index].trim())
    ) {
      paragraph.push(lines[index].trim());
      index += 1;
    }
    blocks.push(<p key={`paragraph-${index}`}><InlineMarkdown text={paragraph.join(" ")} /></p>);
  }
  return <div className="session-chat__formatted">{blocks}</div>;
}

export function SessionChat() {
  const sessionId = useRunStore((state) => state.sessionId);
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    setMessages([]);
    setError(null);
    setQuestion("");
  }, [sessionId]);

  useEffect(() => {
    if (!open) return;
    inputRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open]);

  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [messages, pending]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const text = question.trim();
    if (!sessionId || !text || pending) return;
    const userMessage: DisplayMessage = { id: crypto.randomUUID(), role: "user", content: text };
    const history = messages.map(({ role, content }) => ({ role, content }));
    setMessages((current) => [...current, userMessage]);
    setQuestion("");
    setPending(true);
    setError(null);
    try {
      const response = await api.chatSession(sessionId, text, history);
      setMessages((current) => [
        ...current,
        { id: crypto.randomUUID(), role: "assistant", content: response.answer },
      ]);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="session-chat">
      {open && (
        <section className="session-chat__panel" role="dialog" aria-label="Session observer chat">
          <header className="session-chat__header">
            <div className="session-chat__identity">
              <span className="session-chat__avatar"><ChatbotIcon /></span>
              <div>
                <strong>Session observer</strong>
                <span>Read only · current session evidence</span>
              </div>
            </div>
            <button type="button" className="session-chat__close" onClick={() => setOpen(false)} aria-label="Close session chat">×</button>
          </header>

          <div className="session-chat__messages" ref={listRef} aria-live="polite">
            {messages.length === 0 && (
              <div className="session-chat__intro">
                <strong>Ask about this run</strong>
                <p>I can explain stages, metrics, failures, recoveries, budgets, and the selected model. I cannot change the session.</p>
              </div>
            )}
            {messages.map((message) => (
              <div key={message.id} className={`session-chat__message is-${message.role}`}>
                <span>{message.role === "assistant" ? "Observer" : "You"}</span>
                {message.role === "assistant"
                  ? <FormattedAnswer content={message.content} />
                  : <p>{message.content}</p>}
              </div>
            ))}
            {pending && <div className="session-chat__thinking">Reading session evidence…</div>}
            {error && <div className="session-chat__error" role="alert">{error}</div>}
          </div>

          <form className="session-chat__composer" onSubmit={submit}>
            <textarea
              ref={inputRef}
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
              rows={2}
              maxLength={4000}
              placeholder={sessionId ? "Ask what happened in this session…" : "Select a session first"}
              aria-label="Ask about this session"
              disabled={!sessionId || pending}
            />
            <button type="submit" disabled={!sessionId || !question.trim() || pending}>Send</button>
          </form>
        </section>
      )}

      <button
        type="button"
        className="session-chat__trigger"
        onClick={() => setOpen((value) => !value)}
        disabled={!sessionId}
        aria-expanded={open}
        aria-label={open ? "Close session chat" : "Open session chat"}
        title={sessionId ? "Ask about this session" : "Select a session to use the observer"}
      >
        <ChatbotIcon />
        <span>Ask session</span>
      </button>
    </div>
  );
}
