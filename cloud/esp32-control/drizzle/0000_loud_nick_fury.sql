CREATE TABLE `commands` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`device_id` text NOT NULL,
	`boot_id` text NOT NULL,
	`kind` text NOT NULL,
	`payload` text NOT NULL,
	`request` integer NOT NULL,
	`status` text DEFAULT 'pending' NOT NULL,
	`created_at` integer NOT NULL,
	`expires_at` integer NOT NULL,
	`ack` text
);
--> statement-breakpoint
CREATE INDEX `commands_device_status` ON `commands` (`device_id`,`status`);--> statement-breakpoint
CREATE TABLE `devices` (
	`id` text PRIMARY KEY NOT NULL,
	`boot_id` text NOT NULL,
	`last_seen` integer NOT NULL,
	`states` text NOT NULL,
	`uptime` integer NOT NULL,
	`control_until` integer DEFAULT 0 NOT NULL,
	`lease_owner` text
);
--> statement-breakpoint
CREATE TABLE `login_attempts` (
	`key` text PRIMARY KEY NOT NULL,
	`count` integer NOT NULL,
	`since` integer NOT NULL
);
--> statement-breakpoint
CREATE TABLE `sessions` (
	`hash` text PRIMARY KEY NOT NULL,
	`expires_at` integer NOT NULL
);
--> statement-breakpoint
CREATE TABLE `telemetry` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`device_id` text NOT NULL,
	`ts` integer NOT NULL,
	`states` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `telemetry_device_time` ON `telemetry` (`device_id`,`ts`);