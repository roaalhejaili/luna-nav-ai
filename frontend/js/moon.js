// Artistic, procedurally shaded Moon for the briefing screen. NOT measured terrain or imagery:
// craters and maria are noise functions. The view is tilted toward the south pole, the sun is
// placed low on the polar horizon, and a ring marks the analysed region (lat -90 to -75).

const VERT = `attribute vec2 p; void main(){ gl_Position = vec4(p,0.,1.); }`;

const FRAG = `
precision highp float;
uniform vec2 res; uniform float t; uniform float ring; uniform float tilt;
vec3 hash3(vec3 p){ p=vec3(dot(p,vec3(127.1,311.7,74.7)),dot(p,vec3(269.5,183.3,246.1)),dot(p,vec3(113.5,271.9,124.6))); return fract(sin(p)*43758.5453); }
float n3(vec3 p){ vec3 i=floor(p), f=fract(p); f=f*f*(3.-2.*f);
  float a=hash3(i).x, b=hash3(i+vec3(1,0,0)).x, c=hash3(i+vec3(0,1,0)).x, d=hash3(i+vec3(1,1,0)).x;
  float e=hash3(i+vec3(0,0,1)).x, g=hash3(i+vec3(1,0,1)).x, h=hash3(i+vec3(0,1,1)).x, k=hash3(i+vec3(1,1,1)).x;
  return mix(mix(mix(a,b,f.x),mix(c,d,f.x),f.y), mix(mix(e,g,f.x),mix(h,k,f.x),f.y), f.z); }
float fbm(vec3 p){ float s=0., a=.5; for(int i=0;i<4;i++){ s+=a*n3(p); p*=2.03; a*=.5; } return s; }
float craters(vec3 p){
  vec3 i=floor(p), f=fract(p); float h=0.;
  for(int x=-1;x<=1;x++) for(int y=-1;y<=1;y++) for(int z=-1;z<=1;z++){
    vec3 g=vec3(float(x),float(y),float(z)); vec3 o=hash3(i+g);
    if(o.z<.45) continue;
    float r=.18+.22*o.x; float d=length(g+o*.7+.15-f)/r;
    if(d<1.6){ h += (d<1. ? (d*d-1.)*.55 : 0.) + exp(-pow((d-1.)*4.,2.))*.28; }
  }
  return h; }
float height(vec3 p){ return craters(p*3.)*.5 + craters(p*7.)*.22 + craters(p*16.)*.08 + fbm(p*9.)*.06; }
mat3 rotX(float a){ float c=cos(a), s=sin(a); return mat3(1,0,0, 0,c,s, 0,-s,c); }
mat3 rotY(float a){ float c=cos(a), s=sin(a); return mat3(c,0,-s, 0,1,0, s,0,c); }
void main(){
  vec2 uv=(gl_FragCoord.xy*2.-res)/min(res.x,res.y)*1.08;
  float r2=dot(uv,uv);
  if(r2>1.){ float glow=exp(-(sqrt(r2)-1.)*14.)*.10; gl_FragColor=vec4(vec3(.55,.65,.8)*glow, glow); return; }
  vec3 n=vec3(uv, sqrt(1.-r2));
  mat3 M = rotY(t*.035) * rotX(tilt);           // view -> body (body polar axis = +y)
  vec3 b = M*n;
  float e=.004; vec3 t1=normalize(cross(b,vec3(.3,.9,.1))), t2=cross(b,t1);
  float h0=height(b), h1=height(normalize(b+t1*e)), h2=height(normalize(b+t2*e));
  vec3 bn=normalize(b - (t1*(h1-h0)+t2*(h2-h0))/e*.012);
  vec3 nv=normalize(transpose3(M)*bn);
  vec3 sun=normalize(vec3(.86,-.22,.42));      // low, raking light: polar sun angle
  float lam=max(dot(nv,sun),0.);
  float maria=smoothstep(.52,.62,fbm(b*1.6+vec3(4.)));
  vec3 alb=mix(vec3(.74,.75,.77), vec3(.40,.43,.48), maria*.8)*(.86+.28*fbm(b*22.));
  vec3 col=alb*(lam*1.25) + alb*vec3(.10,.13,.20)*.35;      // faint earthshine fill
  float lat=asin(clamp(b.y,-1.,1.));
  float band=smoothstep(.012,.0,abs(lat+1.309))*ring;      // -75 deg
  float cap=smoothstep(-1.26,-1.36,lat)*ring*.10;
  col=mix(col, vec3(.95,.77,.36), band*.85) + vec3(.95,.77,.36)*cap;
  float limb=pow(n.z,.35);
  gl_FragColor=vec4(col*limb,1.);
}`;

// GLSL ES 1.0 has no transpose(); inject a helper.
const FRAG_SRC = FRAG.replace("mat3 rotX", "mat3 transpose3(mat3 m){ return mat3(m[0][0],m[1][0],m[2][0], m[0][1],m[1][1],m[2][1], m[0][2],m[1][2],m[2][2]); }\nmat3 rotX");

export function mountMoon(canvas) {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const gl = canvas.getContext("webgl", { premultipliedAlpha: false, alpha: true, antialias: true });
  const state = { ring: 1, target: 1, tilt: 0.62 };
  if (!gl) return fallback2d(canvas, state);
  const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s)); return s; };
  let prog;
  try {
    prog = gl.createProgram();
    gl.attachShader(prog, sh(gl.VERTEX_SHADER, VERT)); gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FRAG_SRC));
    gl.linkProgram(prog); if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
  } catch (err) { console.warn("Moon shader unavailable, using 2D fallback:", err); return fallback2d(canvas, state); }
  gl.useProgram(prog);
  const buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(prog, "p"); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  const u = { res: gl.getUniformLocation(prog, "res"), t: gl.getUniformLocation(prog, "t"),
    ring: gl.getUniformLocation(prog, "ring"), tilt: gl.getUniformLocation(prog, "tilt") };
  const start = performance.now(); let raf = 0, visible = true;
  const size = () => { const d = Math.min(devicePixelRatio || 1, 1.5); const r = canvas.getBoundingClientRect();
    canvas.width = Math.max(2, Math.round(r.width * d)); canvas.height = Math.max(2, Math.round(r.height * d)); };
  const draw = () => {
    state.ring += (state.target - state.ring) * 0.08;
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.uniform2f(u.res, canvas.width, canvas.height);
    gl.uniform1f(u.t, reduce ? 8 : (performance.now() - start) / 1000 + 8);
    gl.uniform1f(u.ring, state.ring); gl.uniform1f(u.tilt, state.tilt);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  };
  const loop = () => { draw(); if (!reduce && visible) raf = requestAnimationFrame(loop); };
  new ResizeObserver(() => { size(); draw(); }).observe(canvas);
  size(); loop();
  return {
    setRegionHighlight(on) { state.target = on ? 1 : 0; if (reduce) { state.ring = state.target; draw(); } },
    setActive(on) { visible = on; cancelAnimationFrame(raf); if (on) loop(); },
  };
}

function fallback2d(canvas, state) {
  const ctx = canvas.getContext("2d");
  const draw = () => {
    const r = canvas.getBoundingClientRect(); canvas.width = r.width; canvas.height = r.height;
    const s = Math.min(r.width, r.height) / 2.2, cx = r.width / 2, cy = r.height / 2;
    const g = ctx.createRadialGradient(cx - s * .5, cy + s * .3, s * .1, cx, cy, s);
    g.addColorStop(0, "#d9dbdf"); g.addColorStop(.7, "#7d838c"); g.addColorStop(1, "#262c36");
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(cx, cy, s, 0, Math.PI * 2); ctx.fill();
    if (state.target) { ctx.strokeStyle = "rgba(242,195,91,.8)"; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.ellipse(cx, cy + s * .55, s * .55, s * .2, 0, 0, Math.PI * 2); ctx.stroke(); }
  };
  new ResizeObserver(draw).observe(canvas); draw();
  return { setRegionHighlight(on) { state.target = on ? 1 : 0; draw(); }, setActive() {} };
}
