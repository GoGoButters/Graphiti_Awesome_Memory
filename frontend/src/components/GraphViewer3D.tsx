import { useMemo } from 'react';
import ForceGraph3D from 'react-force-graph-3d';
import SpriteText from 'three-spritetext';
import * as THREE from 'three';

interface GraphViewer3DProps {
    elements: any[];
}

export default function GraphViewer3D({ elements }: GraphViewer3DProps) {
    const graphData = useMemo(() => {
        const nodes: any[] = [];
        const links: any[] = [];
        const nodeDegrees: Record<string, number> = {};
        const nodeIds = new Set<string>();

        // First pass: separate nodes and edges
        elements.forEach(el => {
            if (!el.data.source && !el.data.target) {
                nodes.push({
                    id: el.data.id,
                    name: el.data.label || el.data.id,
                    val: 1
                });
                nodeIds.add(el.data.id);
            }
        });

        // Second pass: process edges and add missing nodes
        elements.forEach(el => {
            if (el.data.source && el.data.target) {
                // Check if source/target nodes exist, if not add them
                if (!nodeIds.has(el.data.source)) {
                    nodes.push({ id: el.data.source, name: 'Unknown', val: 0.5, color: 'gray' });
                    nodeIds.add(el.data.source);
                }
                if (!nodeIds.has(el.data.target)) {
                    nodes.push({ id: el.data.target, name: 'Unknown', val: 0.5, color: 'gray' });
                    nodeIds.add(el.data.target);
                }

                links.push({
                    source: el.data.source,
                    target: el.data.target,
                    name: el.data.label || ''
                });

                // Count degrees
                nodeDegrees[el.data.source] = (nodeDegrees[el.data.source] || 0) + 1;
                nodeDegrees[el.data.target] = (nodeDegrees[el.data.target] || 0) + 1;
            }
        });

        console.log(`GraphViewer3D: ${nodes.length} nodes, ${links.length} links`);

        // Calculate colors based on degree ranking
        // Get all unique degree values and sort them descending
        const uniqueDegrees = Array.from(new Set(Object.values(nodeDegrees))).sort((a, b) => b - a);

        nodes.forEach(node => {
            if (node.color === 'gray') return; // Skip auto-generated nodes

            const degree = nodeDegrees[node.id] || 0;
            node.val = Math.max(1, Math.sqrt(degree) * 2); // Size based on degree

            if (degree === uniqueDegrees[0] && uniqueDegrees[0] > 0) {
                node.color = '#ef4444'; // Red (Tailwind red-500)
            } else if (degree === uniqueDegrees[1] && uniqueDegrees.length > 1) {
                node.color = '#eab308'; // Yellow (Tailwind yellow-500)
            } else if (degree === uniqueDegrees[2] && uniqueDegrees.length > 2) {
                node.color = '#22c55e'; // Green (Tailwind green-500)
            } else {
                node.color = '#3b82f6'; // Blue (Tailwind blue-500)
            }
        });

        return { nodes, links };
    }, [elements]);

    return (
        <div className="w-full h-full bg-gray-900">
            <ForceGraph3D
                graphData={graphData}
                nodeLabel="name"
                nodeColor="color"
                nodeRelSize={6}
                nodeThreeObject={(node: any) => {
                    const group = new THREE.Group();

                    // Create Sphere
                    const geometry = new THREE.SphereGeometry(node.val * 4, 32, 32);
                    const material = new THREE.MeshLambertMaterial({
                        color: node.color || '#3b82f6',
                        transparent: true,
                        opacity: 0.75
                    });
                    const sphere = new THREE.Mesh(geometry, material);
                    group.add(sphere);

                    // Create Text
                    const sprite = new SpriteText(node.name);
                    sprite.color = 'white';
                    sprite.textHeight = Math.max(4, node.val * 2); // Scale text with node
                    sprite.position.set(0, 0, 0); // Center text
                    group.add(sprite);

                    return group;
                }}
                linkColor={() => '#ffffff'}
                linkWidth={1.5}
                linkOpacity={0.6}
                linkDirectionalParticles={2}
                linkDirectionalParticleWidth={2}
                linkDirectionalArrowLength={3.5}
                linkDirectionalArrowRelPos={1}
                backgroundColor="#000000"
            />
        </div>
    );
}
