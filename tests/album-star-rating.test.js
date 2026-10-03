import { describe, expect, it, vi } from 'vitest';

import { createAlbumStarRating } from '../js/album-star-rating.js';

describe('album star rating', () => {
  it('preserves an existing half-star rating', () => {
    const control = createAlbumStarRating(3.5);
    document.body.appendChild(control);

    expect(control.value).toBe('3.5');
    expect(control.querySelector('.album-star-rating-value').textContent).toBe('3.5');
    expect(control.style.getPropertyValue('--album-rating-fill')).toBe('70%');
    expect([...control.querySelectorAll('.album-star-rating-star')].map((star) => (
      star.style.getPropertyValue('--album-star-fill')
    ))).toEqual(['100%', '100%', '100%', '50%', '0%']);
  });

  it('selects every half-star step and emits change', () => {
    const control = createAlbumStarRating(null);
    const onChange = vi.fn();
    control.addEventListener('change', onChange);
    document.body.appendChild(control);

    control.querySelector('[data-value="4.5"]').click();

    expect(control.value).toBe('4.5');
    expect(control.querySelector('.album-star-rating-value').textContent).toBe('4.5');
    expect(onChange).toHaveBeenCalledOnce();
  });

  it('previews on hover and restores the saved value afterward', () => {
    const control = createAlbumStarRating(2);
    document.body.appendChild(control);
    control.querySelector('[data-value="5"]').dispatchEvent(new MouseEvent('mouseenter'));
    expect(control.style.getPropertyValue('--album-rating-fill')).toBe('100%');

    control.querySelector('.album-star-rating-stars').dispatchEvent(new MouseEvent('mouseleave'));
    expect(control.style.getPropertyValue('--album-rating-fill')).toBe('40%');
  });
});
