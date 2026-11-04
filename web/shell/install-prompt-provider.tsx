"use client";

import * as React from "react";

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed"; platform: string }>;
}

interface InstallPromptContextValue {
  canInstall: boolean;
  promptInstall: () => Promise<void>;
  isStandalone: boolean;
  isIOS: boolean;
}

const InstallPromptContext =
  React.createContext<InstallPromptContextValue | null>(null);

function getStandalone(media: MediaQueryList) {
  const navigatorWithStandalone = navigator as Navigator & {
    standalone?: boolean;
  };
  return media.matches || navigatorWithStandalone.standalone === true;
}

function getIOS() {
  return (
    /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)
  );
}

export function InstallPromptProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [installEvent, setInstallEvent] =
    React.useState<BeforeInstallPromptEvent | null>(null);
  const [isStandalone, setIsStandalone] = React.useState(false);
  const [isIOS, setIsIOS] = React.useState(false);

  React.useEffect(() => {
    const media = window.matchMedia("(display-mode: standalone)");
    const updateStandalone = () => setIsStandalone(getStandalone(media));
    const captureInstallEvent = (event: Event) => {
      const installPrompt = event as BeforeInstallPromptEvent;
      installPrompt.preventDefault();
      if (!getStandalone(media)) setInstallEvent(installPrompt);
    };
    const markInstalled = () => {
      setInstallEvent(null);
      setIsStandalone(true);
    };

    media.addEventListener("change", updateStandalone);
    window.addEventListener("beforeinstallprompt", captureInstallEvent);
    window.addEventListener("appinstalled", markInstalled);
    const initialSnapshot = window.requestAnimationFrame(() => {
      setIsIOS(getIOS());
      updateStandalone();
    });

    return () => {
      window.cancelAnimationFrame(initialSnapshot);
      media.removeEventListener("change", updateStandalone);
      window.removeEventListener("beforeinstallprompt", captureInstallEvent);
      window.removeEventListener("appinstalled", markInstalled);
    };
  }, []);

  const promptInstall = React.useCallback(async () => {
    if (!installEvent) return;
    try {
      await installEvent.prompt();
      await installEvent.userChoice;
    } catch {
      // Installation is progressive enhancement; browser failures stay inert.
    } finally {
      setInstallEvent(null);
    }
  }, [installEvent]);

  const value = React.useMemo(
    () => ({
      canInstall: installEvent !== null,
      promptInstall,
      isStandalone,
      isIOS,
    }),
    [installEvent, promptInstall, isStandalone, isIOS],
  );

  return (
    <InstallPromptContext.Provider value={value}>
      {children}
    </InstallPromptContext.Provider>
  );
}

export function useInstallPrompt(): InstallPromptContextValue {
  const value = React.useContext(InstallPromptContext);
  if (!value) {
    throw new Error("useInstallPrompt outside <InstallPromptProvider>");
  }
  return value;
}
