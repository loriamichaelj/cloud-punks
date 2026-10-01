// The only build-time switch (DESIGN.md section 15.5). Off in anything that is not local.
export const DEMO_TOOLS = import.meta.env.VITE_DEMO_TOOLS === 'true';
