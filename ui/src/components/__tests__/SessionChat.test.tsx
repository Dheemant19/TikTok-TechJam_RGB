import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/client", () => ({
  api: {
    chatSession: vi.fn(),
    listSessions: vi.fn(),
    startSession: vi.fn(),
    getSnapshot: vi.fn(),
    getReplay: vi.fn(),
    getExecution: vi.fn(),
    getArtifact: vi.fn(),
    control: vi.fn(),
    packageSession: vi.fn(),
    deleteSession: vi.fn(),
  },
  subscribeToEvents: vi.fn(),
}));

import { api } from "../../api/client";
import { useRunStore } from "../../liveworkflow/runStore";
import { SessionChat } from "../SessionChat";

describe("SessionChat", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useRunStore.setState({ sessionId: "session-chat-test" });
  });

  it("sends a read-only session question and renders the answer", async () => {
    vi.mocked(api.chatSession).mockResolvedValue({
      answer: "### E3 result\n\n**E3's hypothesis** used multi-task learning.\n\n- Primary: `0.603923`\n- Improvement: **0.002351**",
      model: "gpt-5.6-terra-2",
      reasoning_effort: "medium",
      usage: { input_tokens: 10, output_tokens: 12, model_id: "gpt-5.6-terra-2" },
    });
    render(<SessionChat />);

    fireEvent.click(screen.getByRole("button", { name: "Open session chat" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Ask about this session" }), {
      target: { value: "Why did the run stop?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(api.chatSession).toHaveBeenCalledWith(
      "session-chat-test",
      "Why did the run stop?",
      [],
    );
    await waitFor(() => {
      expect(screen.queryByText("E3's hypothesis")).not.toBeNull();
    });
    expect(screen.getByText("E3's hypothesis").tagName).toBe("STRONG");
    expect(screen.getByText("Primary:", { exact: false }).closest("li")).not.toBeNull();
    expect(screen.getByText("0.603923").tagName).toBe("CODE");
  });
});
