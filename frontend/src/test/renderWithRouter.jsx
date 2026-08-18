import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

/**
 * Render a component inside a MemoryRouter so pages that use
 * useNavigate / useParams / useSearchParams work in tests.
 */
export function renderWithRouter(ui, { route = "/", initialEntries = [route] } = {}) {
  return render(<MemoryRouter initialEntries={initialEntries}>{ui}</MemoryRouter>);
}