(async (u) => {
  const set = (el, v) => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, v); el.dispatchEvent(new Event('input', {bubbles: true})); };
  const i = document.querySelectorAll('input');
  set(i[0], u); set(i[1], 'Report-Demo-2026');
  document.querySelector('button[type=submit]').click();
  await new Promise(r => setTimeout(r, 3500));
  return document.title;
})
