import { useLocation, useNavigate } from "react-router-dom";
import { APP_ROUTES, routeIndexFor } from "../data/routeRegistry";

function EdgeChevron({ direction }: { direction: "previous" | "next" }) {
  return (
    <svg width="22" height="30" viewBox="0 0 22 30" fill="none" aria-hidden="true">
      <path
        d={direction === "previous" ? "M15.5 5.5 7 15l8.5 9.5" : "M6.5 5.5 15 15l-8.5 9.5"}
        stroke="currentColor"
        strokeWidth="2.15"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function RouteEdgeNavigation() {
  const location = useLocation();
  const navigate = useNavigate();
  const currentIndex = routeIndexFor(location.pathname);
  const previous = APP_ROUTES[(currentIndex - 1 + APP_ROUTES.length) % APP_ROUTES.length];
  const next = APP_ROUTES[(currentIndex + 1) % APP_ROUTES.length];

  return (
    <nav className="route-edge-navigation" aria-label="Move between application tabs">
      <button
        type="button"
        className="route-edge-navigation__control is-previous"
        onClick={() => navigate(previous.to)}
        aria-label={`Previous tab: ${previous.label}`}
        title={`Previous: ${previous.label}`}
      >
        <EdgeChevron direction="previous" />
      </button>
      <button
        type="button"
        className="route-edge-navigation__control is-next"
        onClick={() => navigate(next.to)}
        aria-label={`Next tab: ${next.label}`}
        title={`Next: ${next.label}`}
      >
        <EdgeChevron direction="next" />
      </button>
    </nav>
  );
}
