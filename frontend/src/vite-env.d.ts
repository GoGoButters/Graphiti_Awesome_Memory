/// <reference types="vite/client" />

declare module 'react-force-graph-3d';

interface ImportMetaEnv {
    readonly VITE_API_BASE_URL: string
}

interface ImportMeta {
    readonly env: ImportMetaEnv
}
