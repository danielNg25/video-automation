interface TopBarProps {
  /** A plain page label (rendered with the default text style) OR a
   *  custom React node (rendered as-is — caller owns styling).
   *  Used for richer headers like the per-video editable title chip. */
  readonly breadcrumb?: React.ReactNode;
  readonly showSearch?: boolean;
  readonly searchPlaceholder?: string;
}

export const TopBar: React.FC<TopBarProps> = ({
  breadcrumb,
  showSearch = false,
  searchPlaceholder = 'Search...',
}) => {
  return (
    <header className="flex items-center w-full px-6 h-12 z-50 bg-[#131315] text-sm tracking-tight border-b border-zinc-800/10 shrink-0">
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
      ) : typeof breadcrumb === 'string' ? (
        <span className="text-sm font-semibold text-on-surface-variant tracking-tight">{breadcrumb}</span>
      ) : breadcrumb ?? null}
    </header>
  );
};
