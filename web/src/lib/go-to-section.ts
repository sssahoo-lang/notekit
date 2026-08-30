/**
 * Jumping to a section, from anywhere that offers the jump.
 *
 * Shared because the section rail and the course map both do it, and the two
 * details that make it correct are easy to leave out of a second copy: honour
 * reduced motion, and move focus so a keyboard user lands where the page went.
 */

export function scrollToSection(index: number): void {
  const target = document.getElementById(`section-${index}`);
  if (!target) return;

  // scrollIntoView ignores prefers-reduced-motion, so a smooth jump across
  // twenty screens would fly past regardless of the setting. Honour it.
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  target.scrollIntoView({
    behavior: reduced ? "auto" : "smooth",
    block: "start",
  });

  // Move focus so keyboard users follow the jump rather than staying put and
  // tabbing from wherever they were.
  const heading = target.querySelector("h2");
  if (heading instanceof HTMLElement) {
    heading.setAttribute("tabindex", "-1");
    heading.focus({ preventScroll: true });
  }
}
