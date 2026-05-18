"use client";
import { useState, useEffect } from "react";

export function LiveIndicator() {
    const [seconds, setSeconds] = useState(0);

    useEffect(() => {
        const interval = setInterval(() => {
            setSeconds(s => {
                if (s >= 300) {
                    window.location.reload();
                    return 0;
                }
                return s + 1;
            });
        }, 1000);
        return () => clearInterval(interval);
    }, []);

    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    const timeStr = mins > 0
        ? `${mins}m ${secs}s ago`
        : `${secs}s ago`;

    return (
        <span className="text-terminal-muted text-xs">
            updated {timeStr}
        </span>
    );
}
