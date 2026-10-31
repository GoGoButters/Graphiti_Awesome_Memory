import { useCallback, useEffect, useMemo, useRef } from 'react';
import ForceGraph3D from 'react-force-graph-3d';
import SpriteText from 'three-spritetext';
import { Group, Mesh, MeshLambertMaterial, SphereGeometry } from 'three';

export interface GraphNode {
    id: string;
    label: string;
    degree: number;
    color?: string;
}

export interface GraphEdge {
    id: string;
    source: string;
    target: string;
    label?: string;
    name?: string;
    invalid?: boolean;
}

interface GraphViewer3DProps {
    nodes: GraphNode[];
    edges: GraphEdge[];
    onNodeClick?: (nodeId: string) => void;
}

const SPRITE_LABEL_COUNT = 40;
const DIRECTIONAL_LINK_LIMIT = 300;

export default function GraphViewer3D({ nodes, edges, onNodeClick }: GraphViewer3DProps) {
    const fgRef = useRef<any>();
    // One shared low-poly geometry + material cache, created outside the render loop
    const sphereGeometry = useMemo(() => new SphereGeometry(1, 8, 8), []);
    const materialCache = useRef(new Map<string, MeshLambertMaterial>());

    useEffect(() => {
        // Dispose shared resources on unmount
        return () => {
            materialCache.current.forEach(m => m.dispose());
            materialCache.current.clear();
            sphereGeometry.dispose();
        };
    }, [sphereGeometry]);

    useEffect(() => {
        if (fgRef.current) {
            // Increase repulsion to separate nodes
            fgRef.current.d3Force('charge')?.strength(-150);
        }
    }, []);

    const graphData = useMemo(() => {
        const nodeIds = new Set(nodes.map(n => n.id));

        // Drop edges pointing at missing nodes and self-loops (no "Unknown" placeholders)
        const links = edges
            .filter(e => e.source !== e.target && nodeIds.has(e.source) && nodeIds.has(e.target))
            .map(e => ({
                id: e.id,
                source: e.source,
                target: e.target,
                name: e.label || e.name || '',
                invalid: !!e.invalid,
            }));

        // Colors based on degree ranking (same as before, now from backend degree)
        const uniqueDegrees = Array.from(new Set(nodes.map(n => n.degree || 0))).sort((a, b) => b - a);
        const colorFor = (degree: number) => {
            if (degree > 0 && degree === uniqueDegrees[0]) return '#ef4444'; // Red (Tailwind red-500)
            if (degree > 0 && uniqueDegrees.length > 1 && degree === uniqueDegrees[1]) return '#eab308'; // Yellow
            if (degree > 0 && uniqueDegrees.length > 2 && degree === uniqueDegrees[2]) return '#22c55e'; // Green
            return '#3b82f6'; // Blue
        };

        const gNodes = nodes.map(n => ({
            id: n.id,
            name: n.label || n.id,
            degree: n.degree || 0,
            color: n.color || colorFor(n.degree || 0),
            val: Math.sqrt(n.degree || 0) + 1,
            showLabel: false,
        }));

        // In-scene SpriteText only for the top nodes by degree; rest rely on hover label
        const topIds = new Set(
            gNodes
                .slice()
                .sort((a, b) => b.degree - a.degree)
                .slice(0, SPRITE_LABEL_COUNT)
                .map(n => n.id)
        );
        gNodes.forEach(n => {
            n.showLabel = topIds.has(n.id);
        });

        return { nodes: gNodes, links };
    }, [nodes, edges]);

    const linkCount = graphData.links.length;
    const showDirectional = linkCount <= DIRECTIONAL_LINK_LIMIT;

    const nodeThreeObject = useCallback(
        (node: any) => {
            const group = new Group();

            let material = materialCache.current.get(node.color);
            if (!material) {
                material = new MeshLambertMaterial({
                    color: node.color,
                    transparent: true,
                    opacity: 0.75,
                });
                materialCache.current.set(node.color, material);
            }

            const sphere = new Mesh(sphereGeometry, material);
            sphere.scale.setScalar(Math.max(1.2, Math.sqrt(node.degree || 0) + 1));
            group.add(sphere);

            if (node.showLabel) {
                const sprite = new SpriteText(node.name);
                sprite.color = 'white';
                sprite.textHeight = 4;
                (sprite as any).renderOrder = 999;
                (sprite as any).material.depthTest = false;
                (sprite as any).material.depthWrite = false;
                group.add(sprite);
            }

            return group;
        },
        [sphereGeometry]
    );

    const linkColor = useCallback(
        (link: any) => (link.invalid ? 'rgba(160,160,160,0.18)' : 'rgba(255,255,255,0.45)'),
        []
    );

    const linkWidth = useCallback(
        (link: any) => (link.invalid ? 0.8 : 1.5),
        []
    );

    return (
        <div className="w-full h-full bg-gray-900">
            <ForceGraph3D
                ref={fgRef}
                graphData={graphData}
                nodeLabel="name"
                nodeRelSize={6}
                nodeThreeObject={nodeThreeObject}
                onNodeClick={onNodeClick ? (node: any) => onNodeClick(node.id) : undefined}
                linkColor={linkColor}
                linkWidth={linkWidth}
                linkDirectionalParticles={showDirectional ? 2 : 0}
                linkDirectionalParticleWidth={showDirectional ? 2 : 0}
                linkDirectionalArrowLength={showDirectional ? 3.5 : 0}
                linkDirectionalArrowRelPos={showDirectional ? 1 : 0}
                warmupTicks={linkCount > 1000 ? 50 : 0}
                cooldownTicks={200}
                backgroundColor="#000000"
            />
        </div>
    );
}
