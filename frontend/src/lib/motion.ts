import { animate, stagger, waapi } from 'animejs'
import { useLayoutEffect, useRef, type DependencyList } from 'react'

const reduced = () => typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches

/** Staggered entrance for children marked `data-reveal` (anime.js on the Web Animations API, so it runs on the
 * browser's own timeline and can never leave content hidden). Content stays visible without JS. */
export function useReveal<T extends HTMLElement>(deps: DependencyList = []) {
  const ref = useRef<T>(null)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el || reduced()) return
    // only the first rows stagger in; long lists must not keep content waiting
    const targets = Array.from(el.querySelectorAll('[data-reveal]')).slice(0, 14)
    if (!targets.length) return
    const a = waapi.animate(targets as HTMLElement[], {
      opacity: { from: 0, to: 1 },
      translate: { from: '0px 10px', to: '0px 0px' },
      duration: 560,
      delay: stagger(45),
      ease: 'outCubic',
    })
    return () => {
      a.revert()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return ref
}

/** Slide an indicator element to a target element's offset within the same container. */
export function slideTo(indicator: HTMLElement | null, target: HTMLElement | null) {
  if (!indicator) return
  if (!target) {
    indicator.style.opacity = '0'
    return
  }
  const top = target.offsetTop
  const height = target.offsetHeight
  if (reduced() || indicator.style.opacity !== '1') {
    indicator.style.transform = `translateY(${top}px)`
    indicator.style.height = `${height}px`
    indicator.style.opacity = '1'
    return
  }
  animate(indicator, { translateY: top, height, duration: 380, ease: 'outExpo' })
}

/** Width grow for score bars. */
export function growBars(root: HTMLElement | null) {
  if (!root || reduced()) return
  const bars = root.querySelectorAll<HTMLElement>('[data-bar]')
  if (bars.length) animate(bars, { scaleX: { from: 0 }, duration: 700, delay: stagger(25), ease: 'outQuart' })
}
