declare namespace Cloudflare {
  interface Env {
    DB?: D1Database;
    ADMIN_USERNAME: string;
    ADMIN_PASSWORD: string;
    DEVICE_KEY: string;
    DEVICE_ID: string;
    BUCKET?: R2Bucket;
  }
}
