import { NavLink } from 'react-router-dom';
import { navItems } from '../data/mockData';

interface SidebarProps {
  readonly collapsed?: boolean;
}

export const Sidebar: React.FC<SidebarProps> = ({ collapsed = false }) => {
  return (
    <aside className="hidden md:flex flex-col h-full py-4 border-r border-zinc-800/20 bg-[#0e0e10] w-64 shrink-0">
      <div className="px-6 mb-8">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded bg-primary-container flex items-center justify-center">
            <span
              className="material-symbols-outlined text-on-primary-container"
              style={{ fontVariationSettings: "'FILL' 1" }}
            >
              precision_manufacturing
            </span>
          </div>
          {!collapsed && (
            <h1 className="text-[#d0bcff] font-black font-mono text-xs uppercase tracking-widest">
              Douyin Auto
            </h1>
          )}
        </div>
      </div>

      <nav className="flex-1 space-y-1 px-3">
        {navItems.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === '/'}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2 transition-all duration-200 font-mono text-xs uppercase tracking-widest ${
                isActive
                  ? 'bg-[#2a2a2c] text-[#d0bcff] border-r-2 border-[#d0bcff]'
                  : 'text-zinc-500 hover:text-zinc-300 hover:bg-[#1c1b1d]'
              }`
            }
          >
            <span className="material-symbols-outlined text-sm">{item.icon}</span>
            {!collapsed && <span>{item.label}</span>}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
};
