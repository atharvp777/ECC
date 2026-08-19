import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FileText } from "lucide-react";
import {
  OrbitButton,
  OrbitInput,
  OrbitBadge,
  OrbitCard,
  OrbitEmptyState,
  OrbitSkeleton,
} from "./index";

describe("OrbitButton", () => {
  it("renders children with the secondary variant by default", () => {
    render(<OrbitButton>Save</OrbitButton>);
    const btn = screen.getByRole("button", { name: "Save" });
    expect(btn).toHaveClass("orbit-btn", "orbit-btn--secondary");
  });

  it("applies variant and size classes", () => {
    render(
      <OrbitButton variant="primary" size="sm">
        Go
      </OrbitButton>
    );
    const btn = screen.getByRole("button", { name: "Go" });
    expect(btn).toHaveClass("orbit-btn--primary", "orbit-btn--sm");
  });

  it("disables and shows a spinner while loading", () => {
    render(
      <OrbitButton loading variant="primary">
        Save
      </OrbitButton>
    );
    const btn = screen.getByRole("button", { name: "Save" });
    expect(btn).toBeDisabled();
    expect(btn).toHaveAttribute("aria-busy", "true");
    expect(btn.querySelector(".orbit-btn__spinner")).toBeInTheDocument();
  });

  it("triggers onClick", async () => {
    const onClick = vi.fn();
    const user = userEvent.setup();
    render(<OrbitButton onClick={onClick}>Save</OrbitButton>);
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});

describe("OrbitInput", () => {
  it("renders a labeled input", () => {
    render(<OrbitInput label="Title" placeholder="Task title" />);
    expect(screen.getByLabelText("Title")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Task title")).toBeInTheDocument();
  });

  it("shows helper text", () => {
    render(<OrbitInput label="Deadline" helper="Must finish by this date" />);
    expect(screen.getByText("Must finish by this date")).toBeInTheDocument();
  });

  it("shows an error and marks the input invalid", () => {
    render(<OrbitInput label="Title" error="Title is required" />);
    const input = screen.getByLabelText("Title");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("Title is required")).toBeInTheDocument();
  });

  it("hides helper text when an error is present", () => {
    render(<OrbitInput label="Title" helper="Optional hint" error="Bad value" />);
    expect(screen.queryByText("Optional hint")).not.toBeInTheDocument();
    expect(screen.getByText("Bad value")).toBeInTheDocument();
  });
});

describe("OrbitBadge", () => {
  it("renders children with the default variant", () => {
    render(<OrbitBadge>Open</OrbitBadge>);
    expect(screen.getByText("Open")).toHaveClass("orbit-badge", "orbit-badge--default");
  });

  it("applies the requested variant", () => {
    render(<OrbitBadge variant="success">Done</OrbitBadge>);
    expect(screen.getByText("Done")).toHaveClass("orbit-badge--success");
  });
});

describe("OrbitCard", () => {
  it("renders children inside an orbit-card", () => {
    render(<OrbitCard>Content</OrbitCard>);
    expect(screen.getByText("Content")).toHaveClass("orbit-card");
  });

  it("supports flush padding", () => {
    render(<OrbitCard flush>Content</OrbitCard>);
    expect(screen.getByText("Content")).toHaveClass("orbit-card--flush");
  });
});

describe("OrbitEmptyState", () => {
  it("renders title, description and action", () => {
    render(
      <OrbitEmptyState
        title="No tasks today"
        description="You're clear."
        action={<button>Ask Orbit</button>}
      />
    );
    expect(screen.getByText("No tasks today")).toBeInTheDocument();
    expect(screen.getByText("You're clear.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ask Orbit" })).toBeInTheDocument();
  });

  it("renders an icon when provided", () => {
    render(<OrbitEmptyState icon={FileText} title="No documents" />);
    expect(screen.getByText("No documents")).toBeInTheDocument();
    expect(document.querySelector(".orbit-empty__icon")).toBeInTheDocument();
  });
});

describe("OrbitSkeleton", () => {
  it("renders with inline dimensions and the base class", () => {
    render(<OrbitSkeleton width={80} height={16} />);
    const skeleton = document.querySelector(".orbit-skeleton");
    expect(skeleton).toHaveStyle({ width: "80px", height: "16px" });
  });

  it("applies the text shape class", () => {
    render(<OrbitSkeleton shape="text" />);
    expect(document.querySelector(".orbit-skeleton")).toHaveClass("orbit-skeleton--text");
  });
});