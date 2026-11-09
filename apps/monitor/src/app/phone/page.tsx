export default function PhonePage() {
  return (
    <main className="shell identity-shell">
      <div className="atmosphere" aria-hidden="true" />
      <header className="top">
        <p className="tag">Phone</p>
        <h1 className="identity-ask">What are you labeling?</h1>
        <p className="identity-note">Tap the top of a wave to jump. Type what you hear. Finish saves it on this computer.</p>
      </header>
      <nav className="identity-choices">
        <a href="/crowd">Crowd · earn an MCU</a>
        <a href="/loud">Loud show</a>
        <a href="/review">Current listen</a>
        <a href="/breaks">Breaks</a>
      </nav>
    </main>
  );
}
