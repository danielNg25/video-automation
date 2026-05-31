export interface NavItem {
  readonly icon: string;
  readonly label: string;
  readonly path: string;
}

export const navItems: readonly NavItem[] = [
  { icon: 'rocket_launch', label: 'Pipeline', path: '/' },
  { icon: 'movie_edit', label: 'Video Studio', path: '/videos' },
  { icon: 'graphic_eq', label: 'Dub Studio', path: '/dub-studio' },
  { icon: 'translate', label: 'Translation Profiles', path: '/profiles' },
  { icon: 'settings', label: 'Settings', path: '/settings' },
];
