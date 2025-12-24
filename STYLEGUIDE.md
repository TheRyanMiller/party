# NYE Party App Style Guide

This document defines the visual design system for the NYE Party slideshow application.

## Color Palette

### Primary Gradient Background
```css
background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
```
Used as the base background throughout the app.

### Accent Colors
| Color | Hex | Usage |
|-------|-----|-------|
| Coral/Red | `#ff6b6b` | Errors, pause state, reject buttons |
| Golden Yellow | `#feca57` | Highlights, warnings, primary CTAs |
| Cyan/Blue | `#48dbfb` | Accent in gradients |
| Mint Green | `#1dd1a1` | Success, approve buttons, playing state |
| Pink | `#ff9ff3` | Confetti accent |

### Text Colors
| Color | Value | Usage |
|-------|-------|-------|
| Primary text | `#fff` or `white` | Main content |
| Secondary text | `rgba(255, 255, 255, 0.8)` | Subtitles, labels |
| Muted text | `rgba(255, 255, 255, 0.5)` | Helper text, timestamps |

## Transparency System

**IMPORTANT**: Use transparent backgrounds with backdrop-filter, NOT solid dark colors.

### Card/Panel Backgrounds
```css
/* Correct - Transparent glass effect */
background: rgba(255, 255, 255, 0.1);
backdrop-filter: blur(10px);
border: 1px solid rgba(255, 255, 255, 0.1);

/* Incorrect - Solid dark background */
background: rgba(30, 30, 50, 0.95);  /* Don't use this */
background: #1e1e32;                  /* Don't use this */
```

### Modal Overlays
```css
/* Background overlay */
background: rgba(0, 0, 0, 0.7);
backdrop-filter: blur(8px);

/* Modal content */
background: rgba(255, 255, 255, 0.1);
backdrop-filter: blur(10px);
```

### Button States
```css
/* Default transparent button */
background: rgba(255, 255, 255, 0.08);
border: 1px solid rgba(255, 255, 255, 0.15);

/* Hover state */
background: rgba(255, 255, 255, 0.15);
border-color: rgba(255, 255, 255, 0.25);
```

## Border Radius

| Element | Radius |
|---------|--------|
| Cards, modals | `20px` or `24px` |
| Buttons, inputs | `10px` or `12px` |
| Small elements (badges, dots) | `6px` or `8px` |
| Circular elements | `50%` |

## Typography

### Font Stack
```css
font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
```

### Heading Sizes
| Element | Size |
|---------|------|
| Page title (h1) | `1.4rem` - `2.2rem` |
| Section heading (h2) | `1.1rem` |
| Card heading | `1.3rem` |
| Body text | `14px` - `16px` |
| Small/helper text | `12px` - `13px` |

### Gradient Text Effect
```css
background: linear-gradient(90deg, #ff6b6b, #feca57, #48dbfb);
-webkit-background-clip: text;
-webkit-text-fill-color: transparent;
background-clip: text;
```

## Shadows & Effects

### Text Shadow (for readability on images)
```css
text-shadow: 2px 2px 10px rgba(0, 0, 0, 0.5);
/* Or for more emphasis */
text-shadow: 2px 2px 20px rgba(0, 0, 0, 0.5);
```

### Box Shadow (hover states)
```css
box-shadow: 0 10px 30px rgba(254, 202, 87, 0.3);
```

### Drop Shadow (images/badges)
```css
filter: drop-shadow(0 4px 20px rgba(0, 0, 0, 0.3));
```

## Animations

### Pulse (for status indicators)
```css
@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
}
animation: pulse 1.5s ease-in-out infinite;
```

### Shimmer (for gradient text)
```css
@keyframes shimmer {
    0% { background-position: 0% 50%; }
    100% { background-position: 300% 50%; }
}
animation: shimmer 3s linear infinite;
```

### Button Pop (click feedback)
```css
@keyframes buttonPop {
    0% { transform: scale(1); }
    30% { transform: scale(0.88); }
    60% { transform: scale(1.03); }
    100% { transform: scale(1); }
}
```

### Transition Timing
```css
/* Standard transitions */
transition: all 0.2s ease;
transition: all 0.3s ease;

/* For progress bars */
transition: width 0.2s linear;
```

## Component Patterns

### Cards
```css
.card {
    background: rgba(255, 255, 255, 0.1);
    border-radius: 20px;
    padding: 20px;
    backdrop-filter: blur(10px);
    border: 1px solid rgba(255, 255, 255, 0.1);
}
```

### Primary Button (CTA)
```css
.btn-primary {
    background: linear-gradient(90deg, #ff6b6b, #feca57);
    color: #1a1a2e;
    border: none;
    border-radius: 12px;
    padding: 16px;
    font-weight: bold;
}
```

### Success Button
```css
.btn-success {
    background: linear-gradient(135deg, #1dd1a1, #10ac84);
    color: white;
}
```

### Status Indicators
```css
/* Playing/Active */
.status-playing {
    background: #1dd1a1;
    box-shadow: 0 0 8px #1dd1a1;
}

/* Paused/Error */
.status-paused {
    background: #ff6b6b;
    box-shadow: 0 0 8px #ff6b6b;
}

/* Pending/Warning */
.status-pending {
    border-left: 4px solid #feca57;
}
```

### List Items
```css
.list-item {
    padding: 12px 15px;
    border-radius: 10px;
    background: rgba(255, 255, 255, 0.05);
}

.list-item:hover {
    background: rgba(255, 255, 255, 0.15);
}

.list-item.current {
    background: rgba(29, 209, 161, 0.3);
    border-left: 3px solid #1dd1a1;
}
```

## Responsive Breakpoints

```css
/* Mobile-first approach */
/* Default styles are for mobile */

/* Tablet and up */
@media (min-width: 600px) {
    /* Larger padding, bigger text */
}

/* Desktop */
@media (max-width: 768px) {
    /* Reduced sizes for smaller screens */
}
```

## Z-Index Scale

| Layer | Z-Index |
|-------|---------|
| Background overlay | `-1` |
| Base content | `1` |
| Floating elements | `2` |
| Modals | `100` |

## Accessibility Notes

- Maintain sufficient contrast with transparent backgrounds
- Use `backdrop-filter: blur()` to ensure text readability over images
- Provide visual feedback for all interactive elements
- Use `touch-action: manipulation` for touch-friendly buttons
