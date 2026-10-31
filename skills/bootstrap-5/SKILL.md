---
name: bootstrap-5
description: Construir interfaces con Bootstrap 5 y React-Bootstrap: grilla, componentes, utilidades, temas y accesibilidad
---

# Bootstrap 5 y React-Bootstrap

Usala para maquetar o revisar interfaces con Bootstrap 5.3, en HTML o en React con `react-bootstrap`.

## Base
- Cargar Bootstrap desde npm (`bootstrap`, `react-bootstrap`) o desde un CDN con **versión fija, `integrity` (SRI)** y `crossorigin`.
- Mobile first: grilla `container` → `row` → `col-{bp}-{n}` con breakpoints `sm md lg xl xxl`; `g-*` para los gutters.
- Preferir utilidades (`d-flex`, `gap-3`, `p-3`, `text-body-secondary`) antes que CSS propio; el CSS propio va en un archivo aparte, sin `!important`.
- Temas: variables CSS `--bs-*` y modo oscuro con `data-bs-theme="dark"`; personalización fina con Sass (`$primary`, `$enable-*`).

## React
- Usar los componentes de `react-bootstrap` (`<Button>`, `<Form.Control>`, `<Modal>`, `<Navbar>`) en vez de manipular el DOM o cargar `bootstrap.bundle.js`.
- Formularios controlados; validación con `isInvalid` + `<Form.Control.Feedback>`.
- Componentes chicos y reutilizables; el estado lo más abajo posible.

## Accesibilidad
- Cada control con `<Form.Label>` o `aria-label`; botones de solo ícono con `aria-label`.
- Modales y menús ya manejan el foco: no romperlo con `tabIndex` arbitrarios.
- Contraste mínimo WCAG AA (4.5:1 para texto normal); no transmitir información solo con color.

## Seguridad
- Nunca `dangerouslySetInnerHTML` con datos del usuario sin sanitizar (DOMPurify).
- Tooltips y popovers con `html: true` necesitan contenido confiable o el sanitizer activado.

Fuentes: documentación oficial https://getbootstrap.com/docs/5.3 y https://react-bootstrap.netlify.app
