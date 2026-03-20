interface TopBarProps {
  readonly title?: string;
  readonly breadcrumb?: string;
  readonly showSearch?: boolean;
  readonly searchPlaceholder?: string;
}

export const TopBar: React.FC<TopBarProps> = ({
  title = 'VideoPrecision',
  breadcrumb,
  showSearch = false,
  searchPlaceholder = 'Search...',
}) => {
  return (
    <header className="flex justify-between items-center w-full px-6 h-14 z-50 bg-[#131315] text-sm tracking-tight border-b border-zinc-800/10 shrink-0">
      <div className="flex items-center gap-4 flex-1">
        {showSearch ? (
          <div className="relative w-full max-w-md">
            <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500 text-lg">
              search
            </span>
            <input
              type="text"
              className="w-full bg-surface-container-low border-none rounded-md pl-10 pr-4 py-1.5 text-xs focus:ring-1 focus:ring-primary/40 placeholder:text-zinc-600 text-on-surface"
              placeholder={searchPlaceholder}
            />
          </div>
        ) : (
          <>
            <span className="text-lg font-bold tracking-tighter text-primary">{title}</span>
            {breadcrumb && (
              <>
                <div className="h-4 w-px bg-outline-variant/30" />
                <div className="flex items-center gap-2 text-on-surface-variant font-medium">
                  <span className="material-symbols-outlined text-sm">home</span>
                  <span className="material-symbols-outlined text-xs">chevron_right</span>
                  <span>{breadcrumb}</span>
                </div>
              </>
            )}
          </>
        )}
      </div>
      <div className="flex items-center gap-4">
        <button className="text-zinc-400 hover:bg-surface-container-high p-2 rounded-full transition-colors active:scale-95 duration-150">
          <span className="material-symbols-outlined">notifications</span>
        </button>
        <button className="text-zinc-400 hover:bg-surface-container-high p-2 rounded-full transition-colors active:scale-95 duration-150">
          <span className="material-symbols-outlined">help</span>
        </button>
        <div className="w-8 h-8 rounded-full bg-secondary-container border border-outline-variant/20 overflow-hidden flex items-center justify-center text-xs font-bold text-on-secondary-container">
          D
        </div>
      </div>
    </header>
  );
};
