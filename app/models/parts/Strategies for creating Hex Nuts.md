A good modeling strategy to cut the chamfers for a hex nut involves creating a realistic, circular, and tapered chamfer that varies in size—maximum at the corners and minimum at the flats—rather than a uniform chamfer applied directly to the hexagonal edges. The most effective methods involve Revolved Cuts or Drafted Extruded Cuts to simulate how nuts are manufactured. [1, 2, 3]  
Here are the best strategies based on CAD software: 
1. The Revolved Cut Method (Most Accurate/Parametric) [4]  
This method is highly robust for SolidWorks, Fusion 360, and Inventor, as it allows for easy changes to the hexagon size later. 

• Step 1: Create the hexagonal prism, extruded to the total nut thickness. 
• Step 2: Sketch a triangle (the profile of the chamfer) on a plane that intersects two opposite corners of the hexagon. 
• Step 3: Use a Revolved Cut around the center axis of the nut. 
• Step 4: Mirror the feature to the other side. [7, 8, 9, 10, 11]  

2. The Drafted Cut-Extrude Method (Fastest) 
This is an efficient approach often used to quickly create the circular chamfer. 

• Step 1: Extrude the hexagonal body. 
• Step 2: Sketch a circle on the top face that is tangent to the midpoint of the flats (a circle inscribed within the polygon). 
• Step 3: Use an Extruded Cut on this circle. 
• Step 4: Enable the Draft option in the cut command, set to 60° (or 30° depending on how the software measures it). 
• Step 5: Flip the side to cut to remove the material outside the circle. [1, 13, 14, 15, 16]  

3. Alternative: Cylinder-to-Hex Method 

• Step 1: Start with a cylinder with the diameter of the hexagon's corner-to-corner dimension. 
• Step 2: Apply a regular chamfer tool to the top and bottom edges of the cylinder. 
• Step 3: Sketch the hexagon on top and perform a cut-extrude to remove the excess material. [17, 18, 19, 20]  

Key Tips for Nut Modeling 

• Chamfer Angle: A 30-degree angle (resulting in a 60-degree cone) is standard for many nut chamfers. 
• Modeling Threads: For 3D printing or high-fidelity renders, ensure the "Modeled" option is checked in the thread tool to include actual geometry, rather than just a cosmetic thread. 
• Mirroring: To save time, only model the chamfer on one side, then use the Mirror tool to duplicate it on the other. [3, 4, 7, 10, 14, 18]  

Using a revolved cut or drafted cut ensures that the chamfer properly interacts with the hexagon, tapering off at the center of each flat, which is essential for a realistic model. [2, 4]  

AI responses may include mistakes.

[1] https://www.youtube.com/watch?v=ua_aS4UDcz4
[2] https://www.reddit.com/r/cad/comments/78njbl/how_to_make_the_edge_of_a_nut_rounded_in_inventor/
[3] https://discourse.mcneel.com/t/how-to-model-a-nut-no-videos-anywhere/166534
[4] https://forums.autodesk.com/t5/fusion-design-validate-document/hex-chamfer/td-p/5866598
[5] https://forums.autodesk.com/t5/fusion-design-validate-document/hex-chamfer/td-p/5866598
[6] https://www.youtube.com/watch?v=Wy9UdOJFoJI
[7] https://forums.autodesk.com/t5/inventor-forum/chamfer-on-hex-part/td-p/9566618
[8] https://www.youtube.com/watch?v=S9ZPcZ8osMY
[9] https://www.instructables.com/How-to-Chamfer-a-Nut-in-Fusion-360/
[10] https://www.youtube.com/watch?v=Xho87HJ-XDo
[11] https://askfilo.com/user-question-answers-smart-solutions/figure-6-shows-an-assembly-drawing-of-a-hexagonal-bolt-and-3336373435333032
[12] https://www.sciencedirect.com/science/article/pii/S0166361515000512
[13] https://grabcad.com/tutorials/tutorial-creating-hex-nut-in-solidworks
[14] https://www.youtube.com/watch?v=2WajjF0aYKI
[15] https://www.emastercam.com/forums/topic/5979-creating-a-hex-in-a-solid-lathe/
[16] https://workforce.libretexts.org/Courses/Centralia_College/TRDS_160%3A_CAD_for_Industry_(Gill_and_Tummeti)/01%3A_Modules/1.04%3A_Module_4_-_Solid_Modelling_II
[17] https://www.alibre.com/forum/index.php?threads/how-do-i-chamfer-face-on-hex-nuts.8950/
[18] https://www.instructables.com/How-to-Chamfer-a-Nut-in-Fusion-360/
[19] https://www.woodworkersjournal.com/hand-chasing-threads-in-wood/
[20] https://www.acemakerspace.org/a-parametric-design-for-3d-printed-boxes/

