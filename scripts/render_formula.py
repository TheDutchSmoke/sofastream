"""Generate the two packages in one tap; @dev is a Homebrew alias."""


def formula(channel, version, url, checksum):
    dev = channel == "dev"
    name = "SofastreamPreview" if dev else "Sofastream"
    executable = "tv-dev" if dev else "tv"
    extra = "sofastream@dev" if dev else "sofastream"
    return f'''class {name} < Formula
  desc "Twitch on Apple TV from a macOS terminal{' (development)' if dev else ''}"
  homepage "https://github.com/TheDutchSmoke/sofastream"
  url "{url}"
  version "{version}"
  sha256 "{checksum}"
  license "MIT"

  depends_on :macos
  depends_on "fzf"
  depends_on "node"
  depends_on "python@3.14"
  depends_on "streamlink"
  depends_on "uv"

  def install
    libexec.install "app", "bin", "VERSION"
    ENV["UV_CACHE_DIR"] = buildpath/"uv-cache"
    ENV["npm_config_cache"] = buildpath/"npm-cache"
    system Formula["uv"].opt_bin/"uv", "venv", "--python",
           Formula["python@3.14"].opt_bin/"python3.14", libexec/"remote-venv"
    system Formula["uv"].opt_bin/"uv", "pip", "install", "--python",
           libexec/"remote-venv/bin/python", "-r", libexec/"app/remote-requirements.txt"
    system Formula["node"].opt_bin/"npm", "ci", "--prefix", libexec/"app/gui-importer",
           "--omit=dev", "--no-audit", "--no-fund"
    bin.install_symlink libexec/"bin/{executable}" => "{executable}"
    bin.install_symlink libexec/"bin/{executable}" => "{extra}"
  end

  def caveats
    <<~EOS
      Start with: {executable}
      VLC on Apple TV needs Remote Playback enabled.
      Pair automatic wake/app launch with: {executable} pair
      Pairing displays a code on the TV; do it when the TV is available.
      Installation does not contact or change your Apple TV.
    EOS
  end

  test do
    assert_match "SofaStream", shell_output("#{{bin}}/{executable} --version")
    assert_match "Twitch", shell_output("#{{bin}}/{executable} --help")
    system libexec/"remote-venv/bin/python", "-c", "import pyatv"
    system Formula["node"].opt_bin/"node", "-e",
           "require('#{{libexec}}/app/gui-importer/node_modules/classic-level')"
  end
end
'''
