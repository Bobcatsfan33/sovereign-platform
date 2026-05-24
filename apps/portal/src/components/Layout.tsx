import { Link, NavLink, Outlet } from "react-router-dom";

import { useAuth } from "../hooks/useAuth";

const navLinks = [
  { to: "/", label: "Catalog", end: true },
  { to: "/instances", label: "Instances" },
  { to: "/compliance", label: "Compliance" },
];

export default function Layout() {
  const { auth, logout } = useAuth();
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <a className="skip-link" href="#main">
        Skip to main content
      </a>
      <header className="bg-slate-900 text-white">
        <nav
          aria-label="Primary"
          className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3"
        >
          <Link to="/" className="flex items-center gap-2 text-lg font-semibold">
            <span aria-hidden className="inline-block h-6 w-6 rounded bg-amber-400" />
            Sovereign Platform
          </Link>
          <ul className="flex items-center gap-1">
            {navLinks.map((l) => (
              <li key={l.to}>
                <NavLink
                  to={l.to}
                  end={l.end}
                  className={({ isActive }) =>
                    `rounded px-3 py-2 text-sm font-medium ${
                      isActive
                        ? "bg-slate-700 text-white"
                        : "text-slate-200 hover:bg-slate-800 hover:text-white"
                    } focus:outline-2 focus:outline-amber-300`
                  }
                >
                  {l.label}
                </NavLink>
              </li>
            ))}
          </ul>
          {auth ? (
            <div className="flex items-center gap-2 text-sm">
              <span className="text-slate-300" title={auth.type}>
                {auth.label}
              </span>
              <button
                type="button"
                onClick={logout}
                className="rounded bg-slate-700 px-3 py-1 text-sm hover:bg-slate-600 focus:outline-2 focus:outline-amber-300"
              >
                Sign out
              </button>
            </div>
          ) : (
            <span className="text-sm text-slate-300">Not signed in</span>
          )}
        </nav>
      </header>
      <main id="main" className="mx-auto max-w-6xl px-4 py-8">
        <Outlet />
      </main>
      <footer className="mx-auto max-w-6xl px-4 py-8 text-sm text-slate-500">
        Sovereign Platform · base chassis v0.1 ·
        <span className="ml-1">
          For service requests not in the catalog, contact your platform team.
        </span>
      </footer>
    </div>
  );
}
