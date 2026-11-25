export function Message({children, ...props}) {
  return <p {...props} hidden={!children}>{children}</p>;
}

export function isPlainNavigation(event) {
  return !event.defaultPrevented && event.button === 0 &&
    !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey;
}
