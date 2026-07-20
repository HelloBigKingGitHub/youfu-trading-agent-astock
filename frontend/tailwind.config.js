// shadcn-style config — colors map to CSS variables defined in tokens.css.
// All design tokens 1:1 mirror web/styles/tokens.css (Bloomberg-glacier-blue dark theme).
var config = {
    darkMode: 'class',
    content: ['./index.html', './src/**/*.{ts,tsx}'],
    theme: {
        extend: {
            colors: {
                // Backgrounds
                'bg-base': 'var(--bg-base)',
                'bg-surface': 'var(--bg-surface)',
                'bg-elevated': 'var(--bg-elevated)',
                'bg-input': 'var(--bg-input)',
                // Borders
                'border-1': 'var(--border-1)',
                'border-2': 'var(--border-2)',
                'border-3': 'var(--border-3)',
                // Text
                'text-primary': 'var(--text-primary)',
                'text-secondary': 'var(--text-secondary)',
                'text-tertiary': 'var(--text-tertiary)',
                // Bloomberg accent
                'bb-accent': 'var(--bb-accent)',
                'bb-accent-bright': 'var(--bb-accent-bright)',
                'bb-accent-dim': 'var(--bb-accent-dim)',
                'bb-accent-glow': 'var(--bb-accent-glow)',
                'bb-accent-soft': 'var(--bb-accent-soft)',
                // Financial state (A 股: 红涨绿跌)
                'bb-up': 'var(--bb-up)',
                'bb-down': 'var(--bb-down)',
                'bb-neutral': 'var(--bb-neutral)',
                // shadcn-style aliases for forms/buttons
                border: 'var(--border-1)',
                input: 'var(--bg-input)',
                ring: 'var(--bb-accent)',
                background: 'var(--bg-base)',
                foreground: 'var(--text-primary)',
                primary: {
                    DEFAULT: 'var(--bb-accent)',
                    foreground: '#ffffff',
                },
                secondary: {
                    DEFAULT: 'var(--bg-elevated)',
                    foreground: 'var(--text-primary)',
                },
                destructive: {
                    DEFAULT: 'var(--bb-up)',
                    foreground: '#ffffff',
                },
                muted: {
                    DEFAULT: 'var(--bg-elevated)',
                    foreground: 'var(--text-secondary)',
                },
                accent: {
                    DEFAULT: 'var(--bb-accent-soft)',
                    foreground: 'var(--bb-accent-bright)',
                },
                popover: {
                    DEFAULT: 'var(--bg-elevated)',
                    foreground: 'var(--text-primary)',
                },
                card: {
                    DEFAULT: 'var(--bg-surface)',
                    foreground: 'var(--text-primary)',
                },
            },
            borderRadius: {
                sm: 'var(--radius-sm)',
                md: 'var(--radius-md)',
                lg: 'var(--radius-lg)',
            },
            boxShadow: {
                sm: 'var(--shadow-sm)',
                md: 'var(--shadow-md)',
                lg: 'var(--shadow-lg)',
            },
            fontFamily: {
                sans: 'var(--font-sans)',
                mono: 'var(--font-mono)',
            },
            keyframes: {
                'accordion-down': {
                    from: { height: '0' },
                    to: { height: 'var(--radix-accordion-content-height)' },
                },
                'accordion-up': {
                    from: { height: 'var(--radix-accordion-content-height)' },
                    to: { height: '0' },
                },
            },
            animation: {
                'accordion-down': 'accordion-down 0.18s ease-out',
                'accordion-up': 'accordion-up 0.18s ease-out',
            },
        },
    },
    plugins: [],
};
export default config;
