/**
 * Contact form schemas: the browser-side form schema and the normalized
 * server-side request schema. Both are strict about the fields they know;
 * the server schema additionally requires the Turnstile token and consent.
 */

import { z } from "zod";

export const contactFormSchema = z.object({
  name: z.string().trim().min(1, "Name is required.").max(100),
  email: z.email("A valid email address is required.").max(254),
  subject: z.string().trim().min(3, "Subject is too short.").max(120),
  message: z
    .string()
    .trim()
    .min(10, "Please write at least 10 characters.")
    .max(5000),
  consent: z.literal(true, {
    error: "Consent is required to send the message.",
  }),
  turnstileToken: z.string().min(1, "Please complete the human check."),
  // Honeypot: a real user never fills this field; it must stay empty.
  website: z.string().max(0).optional(),
});

export type ContactFormValues = z.infer<typeof contactFormSchema>;

export const contactRequestSchema = contactFormSchema.extend({
  turnstileToken: z.string().min(1),
});

export type ContactRequest = z.infer<typeof contactRequestSchema>;

export const contactResponseSchema = z.object({
  ok: z.literal(true),
  request_id: z.string().min(1),
});

export type ContactResponse = z.infer<typeof contactResponseSchema>;

export const contactErrorSchema = z.object({
  error: z.string().min(1),
  request_id: z.string().min(1).nullish(),
});
