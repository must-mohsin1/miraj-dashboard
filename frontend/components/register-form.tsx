"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { CheckCircle2, Eye, EyeOff, Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

const registerSchema = z
  .object({
    username: z
      .string()
      .min(3, "Username must be at least 3 characters")
      .max(32, "Username must be 32 characters or fewer"),
    email: z.string().email("Enter a valid email address"),
    password: z
      .string()
      .min(8, "Password must be at least 8 characters")
      .max(128, "Password must be 128 characters or fewer"),
    confirmPassword: z.string(),
  })
  .refine((data) => data.password === data.confirmPassword, {
    message: "Passwords do not match",
    path: ["confirmPassword"],
  });

type RegisterValues = z.infer<typeof registerSchema>;

/* ── Password strength ─────────────────────────────────────────────────────── */

type StrengthLevel = "weak" | "fair" | "strong";

interface StrengthInfo {
  level: StrengthLevel;
  label: string;
  /** Tailwind classes for the filled segment(s) of the strength bar. */
  barColor: string;
  /** How many of the 3 segments are filled (1–3). */
  filled: number;
}

/**
 * Score a password 0–6 based on common heuristics, then bucket into
 * weak / fair / strong for the indicator bar.
 */
function scorePassword(pw: string): StrengthInfo {
  let score = 0;
  if (pw.length >= 8) score++;
  if (pw.length >= 12) score++;
  if (/[a-z]/.test(pw)) score++;
  if (/[A-Z]/.test(pw)) score++;
  if (/\d/.test(pw)) score++;
  if (/[^A-Za-z0-9]/.test(pw)) score++;

  // 0–2 → weak, 3–4 → fair, 5–6 → strong
  if (score <= 2) {
    return { level: "weak", label: "Weak", barColor: "bg-red-500", filled: 1 };
  }
  if (score <= 4) {
    return { level: "fair", label: "Fair", barColor: "bg-amber-500", filled: 2 };
  }
  return { level: "strong", label: "Strong", barColor: "bg-emerald-500", filled: 3 };
}

/** Small password-strength indicator: 3 segments + a label. */
function PasswordStrength({ password }: { password: string }) {
  if (!password) return null;
  const info = scorePassword(password);
  return (
    <div className="flex items-center gap-2">
      <div className="flex flex-1 gap-1">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className={cn(
              "h-1.5 flex-1 rounded-full transition-colors",
              i < info.filled ? info.barColor : "bg-muted"
            )}
          />
        ))}
      </div>
      <span
        className={cn(
          "w-12 text-right text-xs font-medium",
          info.level === "weak" && "text-red-400",
          info.level === "fair" && "text-amber-400",
          info.level === "strong" && "text-emerald-400"
        )}
      >
        {info.label}
      </span>
    </div>
  );
}

/* ── Component ────────────────────────────────────────────────────────────── */

export function RegisterForm({ className }: { className?: string }) {
  const router = useRouter();
  const [serverError, setServerError] = useState<string | null>(null);
  const [succeeded, setSucceeded] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  // Track the live password value so the strength indicator can update as
  // the user types (independent of react-hook-form's validation cycle).
  const [passwordValue, setPasswordValue] = useState("");

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<RegisterValues>({
    resolver: zodResolver(registerSchema),
    defaultValues: { username: "", email: "", password: "", confirmPassword: "" },
  });

  async function onSubmit(values: RegisterValues) {
    setServerError(null);
    try {
      const res = await fetch("/api/v1/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: values.username,
          email: values.email,
          password: values.password,
        }),
      });

      if (!res.ok) {
        let message = "Registration failed. Please try again.";
        try {
          const data = await res.json();
          if (data?.detail) {
            message =
              typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
          }
        } catch {
          /* keep default message */
        }
        setServerError(message);
        return;
      }

      // Success — show a confirmation state, then redirect to login.
      setSucceeded(true);
      setTimeout(() => {
        router.push("/login?registered=1");
      }, 1500);
    } catch {
      setServerError("Network error. Please check your connection and try again.");
    }
  }

  /* ── Success state ──────────────────────────────────────────────────────── */
  if (succeeded) {
    return (
      <Card className={cn("w-full max-w-md", className)}>
        <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
          <CheckCircle2 className="h-12 w-12 text-emerald-500" />
          <h2 className="text-lg font-semibold text-slate-100">
            Account created!
          </h2>
          <p className="text-sm text-muted-foreground">
            Redirecting you to the sign-in page…
          </p>
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }

  /* ── Form ────────────────────────────────────────────────────────────────── */
  return (
    <Card className={cn("w-full max-w-md", className)}>
      <CardHeader>
        <CardTitle>Create an account</CardTitle>
        <CardDescription>
          Register to start using the Miraj dashboard.
        </CardDescription>
      </CardHeader>
      <form onSubmit={handleSubmit(onSubmit)}>
        <CardContent className="space-y-4">
          {serverError && (
            <div
              role="alert"
              className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive"
            >
              {serverError}
            </div>
          )}
          <div className="space-y-2">
            <Label htmlFor="username">Username</Label>
            <Input
              id="username"
              type="text"
              autoComplete="username"
              placeholder="your-username"
              aria-invalid={!!errors.username}
              {...register("username")}
            />
            {errors.username && (
              <p className="text-sm text-destructive">
                {errors.username.message}
              </p>
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              autoComplete="email"
              placeholder="you@example.com"
              aria-invalid={!!errors.email}
              {...register("email")}
            />
            {errors.email && (
              <p className="text-sm text-destructive">
                {errors.email.message}
              </p>
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor="password">Password</Label>
            <div className="relative">
              <Input
                id="password"
                type={showPassword ? "text" : "password"}
                autoComplete="new-password"
                placeholder="••••••••"
                aria-invalid={!!errors.password}
                className="pr-10"
                {...register("password", {
                  onChange: (e) => setPasswordValue(e.target.value),
                })}
              />
              <button
                type="button"
                onClick={() => setShowPassword((s) => !s)}
                className="absolute inset-y-0 right-0 flex items-center pr-3 text-muted-foreground hover:text-foreground"
                aria-label={showPassword ? "Hide password" : "Show password"}
                tabIndex={-1}
              >
                {showPassword ? (
                  <EyeOff className="h-4 w-4" />
                ) : (
                  <Eye className="h-4 w-4" />
                )}
              </button>
            </div>
            <PasswordStrength password={passwordValue} />
            {errors.password && (
              <p className="text-sm text-destructive">
                {errors.password.message}
              </p>
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor="confirmPassword">Confirm password</Label>
            <div className="relative">
              <Input
                id="confirmPassword"
                type={showConfirm ? "text" : "password"}
                autoComplete="new-password"
                placeholder="••••••••"
                aria-invalid={!!errors.confirmPassword}
                className="pr-10"
                {...register("confirmPassword")}
              />
              <button
                type="button"
                onClick={() => setShowConfirm((s) => !s)}
                className="absolute inset-y-0 right-0 flex items-center pr-3 text-muted-foreground hover:text-foreground"
                aria-label={showConfirm ? "Hide password" : "Show password"}
                tabIndex={-1}
              >
                {showConfirm ? (
                  <EyeOff className="h-4 w-4" />
                ) : (
                  <Eye className="h-4 w-4" />
                )}
              </button>
            </div>
            {errors.confirmPassword && (
              <p className="text-sm text-destructive">
                {errors.confirmPassword.message}
              </p>
            )}
          </div>
        </CardContent>
        <CardFooter className="flex flex-col gap-4">
          <Button
            type="submit"
            className="w-full"
            disabled={isSubmitting}
          >
            {isSubmitting ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Creating account…
              </>
            ) : (
              "Register"
            )}
          </Button>
          <p className="text-center text-sm text-muted-foreground">
            Already have an account?{" "}
            <Link
              href="/login"
              className="font-medium text-foreground underline-offset-4 hover:underline"
            >
              Log in
            </Link>
          </p>
        </CardFooter>
      </form>
    </Card>
  );
}
