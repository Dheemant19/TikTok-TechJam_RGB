export interface AppRouteDefinition {
  to: string;
  label: string;
  shortLabel: string;
  primary: boolean;
}

export const APP_ROUTES: AppRouteDefinition[] = [
  { to: "/", label: "Live Workflow", shortLabel: "Live", primary: true },
  { to: "/data-profile", label: "Data Profile", shortLabel: "Data", primary: true },
  { to: "/experiments", label: "Experiments", shortLabel: "Experiments", primary: true },
  { to: "/research", label: "Research Library", shortLabel: "Research", primary: true },
  { to: "/resources", label: "Resources", shortLabel: "Resources", primary: true },
  { to: "/package", label: "Final Package", shortLabel: "Package", primary: true },
  { to: "/autonomy", label: "Autonomy Log", shortLabel: "Autonomy", primary: false },
];

export const PRIMARY_ROUTES = APP_ROUTES.filter((route) => route.primary);

export function routeIndexFor(pathname: string): number {
  const index = APP_ROUTES.findIndex((route) =>
    route.to === "/" ? pathname === "/" : pathname.startsWith(route.to),
  );
  return index < 0 ? 0 : index;
}
