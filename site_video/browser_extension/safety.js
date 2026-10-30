// Whether sending to `server` would put a sign-in on the network unencrypted: plain http to anything but this computer.
function isInsecureRemote(server) {
  let u;
  try { u = new URL(server); } catch { return false; }
  if (u.protocol !== "http:") return false;
  const h = u.hostname.replace(/^\[|\]$/g, "").toLowerCase();
  return !(h === "localhost" || h === "::1" || /^127(\.\d{1,3}){3}$/.test(h));
}
if (typeof module !== "undefined") module.exports = {isInsecureRemote};
